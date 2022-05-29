import logging

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.db.models.signals import post_save
from django.db.transaction import atomic
from django.dispatch import receiver

from ..models import get_treasury_account
from ..models.accounting import PaymentNetworkAccount, UserAccount
from ..models.networks import InternalPaymentNetwork, PaymentNetwork
from ..models.payments import PaymentConfirmation
from ..models.transfers import (
    Transfer,
    TransferCancellation,
    TransferConfirmation,
    TransferFailure,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save)
def on_payment_network_created_create_account(sender, **kw):
    if not issubclass(sender, PaymentNetwork):
        return

    network = kw["instance"]
    if kw["created"]:
        PaymentNetworkAccount.objects.get_or_create(network=network)


@receiver(post_save, sender=Site)
def on_site_saved_make_payment_network(sender, **kw):
    site = kw["instance"]
    InternalPaymentNetwork.objects.update_or_create(
        site=site, defaults={"name": f"{site.name} Treasury"}
    )


@receiver(post_save, sender=User)
def on_user_created_create_account(sender, **kw):
    if kw["created"]:
        UserAccount.objects.get_or_create(user=kw["instance"])


# Internal movements
@atomic()
@receiver(post_save)
def on_transfer_created_move_funds_from_sender_to_treasury(sender, **kw):
    if not issubclass(sender, Transfer):
        return

    if kw["created"]:
        transfer = kw["instance"]
        params = dict(reference=transfer, currency=transfer.currency, amount=transfer.amount)

        treasury = get_treasury_account()

        user_book = transfer.sender.account.get_book(token=transfer.currency)
        treasury_book = treasury.get_book(token=transfer.currency)

        user_book.debits.create(**params)
        treasury_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=TransferConfirmation)
def on_internal_transfer_confirmed_move_funds_from_treasury_to_receiver(sender, **kw):

    if kw["created"]:
        confirmation = kw["instance"]
        transfer = confirmation.transfer.internaltransfer

        treasury = get_treasury_account()
        params = dict(reference=transfer, currency=transfer.currency, amount=transfer.amount)

        treasury_book = treasury.get_book(token=transfer.currency)
        receiver_book = transfer.receiver.account.get_book(token=transfer.currency)

        treasury_book.debits.create(**params)
        receiver_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=PaymentConfirmation)
def on_payment_confirmed_move_funds_from_treasury_to_payee(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        payment = confirmation.payment

        params = dict(reference=confirmation, amount=payment.amount, currency=payment.currency)
        treasury = get_treasury_account()
        treasury_book = treasury.get_book(token=payment.currency)
        payee_book = payment.route.deposit.user.account.get_book(token=payment.currency)

        treasury_book.debits.create(**params)
        payee_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=TransferFailure)
@receiver(post_save, sender=TransferCancellation)
def on_reverted_transaction_move_funds_from_treasury_to_sender(sender, **kw):
    if kw["created"]:
        transfer_action = kw["instance"]
        transfer = transfer_action.transfer

        if transfer.is_processed:
            logger.critical(f"{transfer} has already been processed, yet has {transfer_action}")
            return

        try:
            treasury = get_treasury_account()
            treasury_book = treasury.get_book(token=transfer.currency)

            sender_book = transfer.sender.account.get_book(token=transfer.currency)
            treasury_book.debits.create(
                reference=transfer_action, currency=transfer.currency, amount=transfer.amount
            )
            sender_book.credits.create(
                reference=transfer_action, currency=transfer.currency, amount=transfer.amount
            )

        except Exception as exc:
            logger.exception(exc)


__all__ = [
    "on_payment_network_created_create_account",
    "on_site_saved_make_payment_network",
    "on_user_created_create_account",
    "on_transfer_created_move_funds_from_sender_to_treasury",
    "on_internal_transfer_confirmed_move_funds_from_treasury_to_receiver",
    "on_payment_confirmed_move_funds_from_treasury_to_payee",
    "on_reverted_transaction_move_funds_from_treasury_to_sender",
]
