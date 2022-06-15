import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.db.transaction import atomic
from django.dispatch import receiver

from hub20.apps.core.models import get_treasury_account
from hub20.apps.core.models.payments import PaymentConfirmation

# FIXME: need to find a better distinction between Payment / RaidenPayment
# Payment -> the record of the payment on the node
# RaidenPayment -> a payment made to the Hub done on the route provided
from .models import (
    Payment,
    Raiden,
    RaidenPayment,
    RaidenPaymentNetwork,
    RaidenPaymentRoute,
    RaidenProvider,
    RaidenTransfer,
    RaidenTransferConfirmation,
)
from .signals import raiden_payment_received, raiden_payment_sent

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Raiden)
def on_raiden_created_create_payment_network(sender, **kw):
    raiden = kw["instance"]
    if kw["created"]:
        RaidenPaymentNetwork.objects.update_or_create(
            chain=raiden.chain,
            defaults={"name": f"Raiden @ {raiden.chain.name}"},
        )


@receiver(post_save, sender=RaidenPaymentNetwork)
def on_raiden_payment_network_created_create_provider(sender, **kw):
    network = kw["instance"]
    if kw["created"]:
        RaidenProvider.objects.update_or_create(
            network=network, defaults={"raiden": network.chain.raiden_node}
        )


@receiver(post_save, sender=Payment)
def on_payment_created_check_received(sender, **kw):
    payment = kw["instance"]
    if kw["created"]:
        if payment.receiver_address == payment.channel.raiden.address:
            logger.info(f"New payment received by {payment.channel}")
            raiden_payment_received.send(sender=Payment, payment=payment)


@receiver(post_save, sender=Payment)
def on_payment_created_check_sent(sender, **kw):
    payment = kw["instance"]
    if kw["created"]:
        if payment.sender_address == payment.channel.raiden.address:
            logger.info(f"New payment sent by {payment.channel}")
            raiden_payment_sent.send(sender=Payment, payment=payment)


@receiver(raiden_payment_received, sender=Payment)
def on_raiden_payment_received_check_raiden_payments(sender, **kw):
    raiden_payment = kw["payment"]

    if RaidenPayment.objects.filter(payment=raiden_payment).exists():
        logger.info(f"Payment {raiden_payment} is already recorded")
        return

    payment_route = RaidenPaymentRoute.objects.filter(
        identifier=raiden_payment.identifier,
        raiden=raiden_payment.channel.raiden,
    ).first()

    if payment_route is not None:
        amount = raiden_payment.as_token_amount
        RaidenPayment.objects.create(
            route=payment_route,
            amount=amount.amount,
            currency=raiden_payment.token,
            payment=raiden_payment,
        )


@receiver(post_save, sender=RaidenPayment)
def on_raiden_payment_create_confirmation(sender, **kw):
    if kw["created"]:
        PaymentConfirmation.objects.create(payment=kw["instance"])


@receiver(post_save, sender=Payment)
def on_raiden_payment_sent_record_confirmation(sender, **kw):
    if kw["created"]:
        payment = kw["instance"]

        transfer = RaidenTransfer.processed.filter(
            amount=payment.amount,
            currency=payment.token,
            address=payment.receiver_address,
            receipt__raidentransferreceipt__payment_data__identifier=payment.identifier,
        ).first()

        if transfer:
            RaidenTransferConfirmation.objects.create(transfer=transfer, payment=payment)


# Accounting
@atomic()
@receiver(post_save, sender=RaidenPayment)
def on_raiden_payment_received_move_funds_from_raiden_to_treasury(sender, **kw):
    if kw["created"]:
        raiden_payment = kw["instance"]
        payment = raiden_payment.payment
        raiden = payment.channel.raiden

        is_received = payment.receiver_address == raiden.address

        if is_received:
            payment_type = ContentType.objects.get_for_model(payment)
            params = dict(
                reference_type=payment_type,
                reference_id=payment.id,
                currency=payment.token,
                amount=payment.amount,
            )

            treasury = get_treasury_account()
            raiden_account = raiden.chain.raidenpaymentnetwork.account

            treasury_book = treasury.get_book(token=payment.token)
            raiden_book = raiden_account.get_book(token=payment.token)

            treasury_book.credits.get_or_create(**params)
            raiden_book.debits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=RaidenTransferConfirmation)
def on_raiden_transfer_confirmed_move_funds_from_treasury_to_raiden(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        transfer = confirmation.transfer

        transfer_type = ContentType.objects.get_for_model(transfer)
        params = dict(
            reference_type=transfer_type,
            reference_id=transfer.id,
            currency=transfer.currency,
            amount=transfer.amount,
        )

        treasury = get_treasury_account()
        raiden_account = transfer.currency.subclassed.chain.raidenpaymentnetwork.account

        treasury_book = treasury.get_book(token=transfer.currency)
        raiden_book = raiden_account.get_book(token=transfer.currency)

        treasury_book.debits.get_or_create(**params)
        raiden_book.credits.get_or_create(**params)


__all__ = [
    "on_raiden_created_create_payment_network",
    "on_payment_created_check_received",
    "on_payment_created_check_sent",
    "on_raiden_payment_received_check_raiden_payments",
    "on_raiden_payment_create_confirmation",
    "on_raiden_payment_sent_record_confirmation",
    "on_raiden_payment_received_move_funds_from_raiden_to_treasury",
    "on_raiden_transfer_confirmed_move_funds_from_treasury_to_raiden",
]
