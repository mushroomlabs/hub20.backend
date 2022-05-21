import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from hub20.apps.core.models.payments import PaymentConfirmation

# FIXME: need to find a better distinction between Payment / RaidenPayment
# Payment -> the record of the payment on the node
# RaidenPayment -> a payment made to the Hub done on the route provided
from .models import (
    Payment,
    RaidenPayment,
    RaidenPaymentRoute,
    RaidenWithdrawal,
    RaidenWithdrawalConfirmation,
)
from .signals import raiden_payment_received, raiden_payment_sent

logger = logging.getLogger(__name__)


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

        transfer = RaidenWithdrawal.processed.filter(
            amount=payment.amount,
            currency=payment.token,
            address=payment.receiver_address,
            receipt__raidenwithdrawalreceipt__payment_data__identifier=payment.identifier,
        ).first()

        if transfer:
            RaidenWithdrawalConfirmation.objects.create(transfer=transfer, payment=payment)


__all__ = [
    "on_payment_created_check_received",
    "on_payment_created_check_sent",
    "on_raiden_payment_received_check_raiden_payments",
    "on_raiden_payment_create_confirmation",
    "on_raiden_payment_sent_record_confirmation",
]
