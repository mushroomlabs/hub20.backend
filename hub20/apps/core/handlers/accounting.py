import logging

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.db.transaction import atomic
from django.dispatch import receiver

from hub20.apps.blockchain.models import Transaction
from hub20.apps.core.choices import PAYMENT_NETWORKS
from hub20.apps.core.models.accounting import PaymentNetworkAccount, UserAccount
from hub20.apps.core.models.payments import PaymentConfirmation
from hub20.apps.core.models.transfers import (
    BlockchainWithdrawalConfirmation,
    RaidenWithdrawalConfirmation,
    Transfer,
    TransferCancellation,
    TransferConfirmation,
    TransferFailure,
)
from hub20.apps.ethereum_money.signals import incoming_transfer_mined, outgoing_transfer_mined
from hub20.apps.raiden.models import Payment as RaidenPayment

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def on_user_created_create_account(sender, **kw):
    if kw["created"]:
        UserAccount.objects.get_or_create(user=kw["instance"])


# In-Flows
@atomic()
@receiver(incoming_transfer_mined, sender=Transaction)
def on_incoming_transfer_mined_move_funds_from_blockchain_to_treasury(sender, **kw):
    amount = kw["amount"]
    transaction = kw["transaction"]

    transaction_type = ContentType.objects.get_for_model(transaction)

    params = dict(
        reference_type=transaction_type,
        reference_id=transaction.id,
        currency=amount.currency,
        amount=amount.amount,
    )
    blockchain_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.blockchain)
    treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)

    blockchain_book = blockchain_account.get_book(token=amount.currency)
    treasury_book = treasury.get_book(token=amount.currency)

    blockchain_book.debits.get_or_create(**params)
    treasury_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=RaidenPayment)
def on_raiden_payment_received_move_funds_from_raiden_to_treasury(sender, **kw):
    if kw["created"]:
        payment = kw["instance"]
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

            treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
            raiden_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.raiden)

            treasury_book = treasury.get_book(token=payment.token)
            raiden_book = raiden_account.get_book(token=payment.token)

            treasury_book.credits.get_or_create(**params)
            raiden_book.debits.get_or_create(**params)


# Out-flows
@atomic()
@receiver(outgoing_transfer_mined, sender=Transaction)
def on_outgoing_transfer_mined_move_funds_from_treasury_to_blockchain(sender, **kw):
    transaction = kw["transaction"]
    amount = kw["amount"]

    transaction_type = ContentType.objects.get_for_model(transaction)

    params = dict(
        reference_type=transaction_type,
        reference_id=transaction.id,
        currency=amount.currency,
        amount=amount.amount,
    )
    blockchain_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.blockchain)
    treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)

    treasury_book = treasury.get_book(token=amount.currency)
    blockchain_book = blockchain_account.get_book(token=amount.currency)

    treasury_book.debits.get_or_create(**params)
    blockchain_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=RaidenWithdrawalConfirmation)
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

        treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
        raiden_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.raiden)

        treasury_book = treasury.get_book(token=transfer.currency)
        raiden_book = raiden_account.get_book(token=transfer.currency)

        treasury_book.debits.get_or_create(**params)
        raiden_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=BlockchainWithdrawalConfirmation)
def on_blockchain_transfer_confirmed_move_funds_from_treasury_to_blockchain(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        transaction = confirmation.transaction
        transfer = confirmation.transfer

        treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
        blockchain_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.blockchain)

        blockchain_book = blockchain_account.get_book(token=transfer.currency)
        treasury_book = treasury.get_book(token=transfer.currency)

        transaction_type = ContentType.objects.get_for_model(transaction)
        params = dict(
            reference_type=transaction_type,
            reference_id=transaction.id,
            currency=transfer.currency,
            amount=transfer.amount,
        )

        treasury_book.debits.get_or_create(**params)
        blockchain_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=BlockchainWithdrawalConfirmation)
def on_blockchain_transfer_confirmed_move_fee_from_sender_to_blockchain(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        transaction = confirmation.transaction

        fee = confirmation.fee
        native_token = confirmation.fee.currency

        treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
        blockchain_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.blockchain)

        blockchain_book = blockchain_account.get_book(token=native_token)
        treasury_book = treasury.get_book(token=native_token)
        sender_book = confirmation.transfer.sender.account.get_book(token=native_token)

        transaction_type = ContentType.objects.get_for_model(transaction)
        params = dict(
            reference_type=transaction_type,
            reference_id=transaction.id,
            currency=native_token,
            amount=fee.amount,
        )

        # All transfers from users are mediated by the treasury account
        # and we might add the case where the hub operator pays for transfers.

        sender_book.debits.get_or_create(**params)
        treasury_book.credits.get_or_create(**params)

        treasury_book.debits.get_or_create(**params)
        blockchain_book.credits.get_or_create(**params)


# Internal movements
@atomic()
@receiver(post_save)
def on_transfer_created_move_funds_from_sender_to_treasury(sender, **kw):
    if not issubclass(sender, Transfer):
        return

    if kw["created"]:
        transfer = kw["instance"]
        params = dict(reference=transfer, currency=transfer.currency, amount=transfer.amount)

        treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)

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

        treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
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
            treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
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
            treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
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
    "on_incoming_transfer_mined_move_funds_from_blockchain_to_treasury",
    "on_raiden_payment_received_move_funds_from_raiden_to_treasury",
    "on_outgoing_transfer_mined_move_funds_from_treasury_to_blockchain",
    "on_raiden_transfer_confirmed_move_funds_from_treasury_to_raiden",
    "on_blockchain_transfer_confirmed_move_funds_from_treasury_to_blockchain",
    "on_blockchain_transfer_confirmed_move_fee_from_sender_to_blockchain",
    "on_transfer_created_move_funds_from_sender_to_treasury",
    "on_internal_transfer_confirmed_move_funds_from_treasury_to_receiver",
    "on_payment_confirmed_move_funds_from_treasury_to_payee",
    "on_reverted_transaction_move_funds_from_treasury_to_sender",
]
