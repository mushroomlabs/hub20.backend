import logging

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.db.transaction import atomic
from django.dispatch import receiver

from hub20.apps.blockchain.models import BaseEthereumAccount, Transaction
from hub20.apps.core.models.accounting import (
    ExternalAddressAccount,
    RaidenClientAccount,
    Treasury,
    UserAccount,
)
from hub20.apps.core.models.payments import PaymentConfirmation
from hub20.apps.core.models.transfers import (
    BlockchainWithdrawalConfirmation,
    RaidenWithdrawalConfirmation,
    Transfer,
    TransferCancellation,
    TransferConfirmation,
    TransferFailure,
)
from hub20.apps.ethereum_money.models import EthereumToken
from hub20.apps.ethereum_money.signals import incoming_transfer_mined, outgoing_transfer_mined
from hub20.apps.raiden.models import Payment as RaidenPayment, Raiden

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def on_user_created_create_account(sender, **kw):
    if kw["created"]:
        UserAccount.objects.get_or_create(user=kw["instance"])


@receiver(post_save, sender=Raiden)
def on_raiden_created_create_account(sender, **kw):
    if kw["created"]:
        RaidenClientAccount.objects.get_or_create(raiden=kw["instance"])


# In-Flows
@atomic()
@receiver(incoming_transfer_mined, sender=Transaction)
def on_incoming_transfer_mined_move_funds_from_external_address_to_treasury(sender, **kw):
    amount = kw["amount"]
    transaction = kw["transaction"]

    transaction_type = ContentType.objects.get_for_model(transaction)

    params = dict(
        reference_type=transaction_type,
        reference_id=transaction.id,
        currency=amount.currency,
        amount=amount.amount,
    )
    external_address_account, _ = ExternalAddressAccount.objects.get_or_create(
        address=transaction.from_address
    )
    treasury = Treasury.make()

    external_address_book = external_address_account.get_book(token=amount.currency)
    treasury_book = treasury.get_book(token=amount.currency)

    external_address_book.debits.get_or_create(**params)
    treasury_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=RaidenPayment)
def on_raiden_payment_received_move_funds_from_external_address_to_raiden(sender, **kw):
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

            external_address_account, _ = ExternalAddressAccount.objects.get_or_create(
                address=payment.sender_address
            )

            external_account_book = external_address_account.get_book(token=payment.token)
            raiden_book = raiden.raiden_account.get_book(token=payment.token)

            external_account_book.debits.get_or_create(**params)
            raiden_book.credits.get_or_create(**params)


# Out-flows
@atomic()
@receiver(outgoing_transfer_mined, sender=Transaction)
def on_outgoing_transfer_mined_move_funds_from_treasury_to_external_address(sender, **kw):
    transaction = kw["transaction"]
    amount = kw["amount"]
    address = kw["address"]

    transaction_type = ContentType.objects.get_for_model(transaction)

    params = dict(
        reference_type=transaction_type,
        reference_id=transaction.id,
        currency=amount.currency,
        amount=amount.amount,
    )
    external_account, _ = ExternalAddressAccount.objects.get_or_create(address=address)
    treasury = Treasury.make()

    treasury_book = treasury.get_book(token=amount.currency)
    external_account_book = external_account.get_book(token=amount.currency)

    treasury_book.debits.get_or_create(**params)
    external_account_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=RaidenWithdrawalConfirmation)
def on_raiden_transfer_confirmed_move_funds_from_raiden_to_external_address(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        transfer = confirmation.transfer

        payment = confirmation.raidenwithdrawalconfirmation.payment
        transfer_type = ContentType.objects.get_for_model(transfer)
        params = dict(
            reference_type=transfer_type,
            reference_id=transfer.id,
            currency=transfer.currency,
            amount=transfer.amount,
        )

        external_account, _ = ExternalAddressAccount.objects.get_or_create(
            address=transfer.address
        )

        external_account_book = external_account.get_book(token=transfer.currency)
        raiden_book = payment.channel.raiden.raiden_account.get_book(token=transfer.currency)

        raiden_book.debits.get_or_create(**params)
        external_account_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=BlockchainWithdrawalConfirmation)
def on_blockchain_transfer_confirmed_move_fee_from_sender_to_treasury(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        transaction = confirmation.transaction

        fee = confirmation.fee
        native_token = confirmation.fee.currency

        treasury = Treasury.make()
        treasury_book = treasury.get_book(token=native_token)
        sender_book = confirmation.transfer.sender.account.get_book(token=native_token)

        transaction_type = ContentType.objects.get_for_model(transaction)
        params = dict(
            reference_type=transaction_type,
            reference_id=transaction.id,
            currency=native_token,
            amount=fee.amount,
        )

        sender_book.debits.get_or_create(**params)
        treasury_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=Transaction)
def on_transaction_submitted_move_fee_from_treasury_to_fee_account(sender, **kw):
    if kw["created"]:
        transaction = kw["instance"]

        wallet = BaseEthereumAccount.objects.filter(address=transaction.from_address).first()
        if not wallet:
            return

        native_token = EthereumToken.make_native(chain=transaction.block.chain)
        fee = native_token.from_wei(transaction.gas_fee)
        fee_account = ExternalAddressAccount.get_transaction_fee_account()
        treasury = Treasury.make()

        treasury_book = treasury.get_book(token=native_token)
        fee_book = fee_account.get_book(token=native_token)

        transaction_type = ContentType.objects.get_for_model(transaction)
        params = dict(
            reference_type=transaction_type,
            reference_id=transaction.id,
            currency=native_token,
            amount=fee.amount,
        )

        treasury_book.debits.get_or_create(**params)
        fee_book.credits.get_or_create(**params)


# Internal movements
@atomic()
@receiver(post_save)
def on_transfer_created_move_funds_from_sender_to_treasury(sender, **kw):
    if not issubclass(sender, Transfer):
        return

    if kw["created"]:
        transfer = kw["instance"]
        params = dict(reference=transfer, currency=transfer.currency, amount=transfer.amount)

        treasury = Treasury.make()

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

        treasury = Treasury.make()
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
            treasury = Treasury.make()
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
            treasury = Treasury.make()
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
    "on_raiden_created_create_account",
    "on_incoming_transfer_mined_move_funds_from_external_address_to_treasury",
    "on_raiden_payment_received_move_funds_from_external_address_to_raiden",
    "on_outgoing_transfer_mined_move_funds_from_treasury_to_external_address",
    "on_raiden_transfer_confirmed_move_funds_from_raiden_to_external_address",
    "on_blockchain_transfer_confirmed_move_fee_from_sender_to_treasury",
    "on_transaction_submitted_move_fee_from_treasury_to_fee_account",
    "on_transfer_created_move_funds_from_sender_to_treasury",
    "on_internal_transfer_confirmed_move_funds_from_treasury_to_receiver",
    "on_payment_confirmed_move_funds_from_treasury_to_payee",
    "on_reverted_transaction_move_funds_from_treasury_to_sender",
]
