import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.db.transaction import atomic
from django.dispatch import receiver

from hub20.apps.core import PAYMENT_NETWORK_NAME as CORE_PAYMENT_NETWORK
from hub20.apps.core.models.accounting import PaymentNetworkAccount, UserAccount
from hub20.apps.core.models.payments import PaymentConfirmation
from hub20.apps.core.models.transfers import (
    Transfer,
    TransferCancellation,
    TransferConfirmation,
    TransferFailure,
)

logger = logging.getLogger(__name__)
User = get_user_model()


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

        treasury = PaymentNetworkAccount.make(CORE_PAYMENT_NETWORK)

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

        treasury = PaymentNetworkAccount.make(CORE_PAYMENT_NETWORK)
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

        is_raiden_payment = hasattr(payment.route, "raidenpaymentroute")
        is_blockchain_payment = hasattr(payment.route, "blockchainpaymentroute")

        if is_raiden_payment or is_blockchain_payment:
            params = dict(reference=confirmation, amount=payment.amount, currency=payment.currency)
            treasury = PaymentNetworkAccount.make(CORE_PAYMENT_NETWORK)
            treasury_book = treasury.get_book(token=payment.currency)
            payee_book = payment.route.deposit.user.account.get_book(token=payment.currency)

            treasury_book.debits.create(**params)
            payee_book.credits.create(**params)
        else:
            logger.info(f"Payment {payment} was not routed through any external network")


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
            treasury = PaymentNetworkAccount.make(CORE_PAYMENT_NETWORK)
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
    "on_user_created_create_account",
    "on_transfer_created_move_funds_from_sender_to_treasury",
    "on_internal_transfer_confirmed_move_funds_from_treasury_to_receiver",
    "on_payment_confirmed_move_funds_from_treasury_to_payee",
    "on_reverted_transaction_move_funds_from_treasury_to_sender",
]
