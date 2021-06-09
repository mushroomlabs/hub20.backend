import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.db.transaction import atomic
from django.dispatch import receiver

from hub20.apps.blockchain.models import BaseEthereumAccount, Chain, Transaction
from hub20.apps.core.models.accounting import (
    ExternalAddressAccount,
    RaidenClientAccount,
    Treasury,
    UserAccount,
    WalletAccount,
)
from hub20.apps.core.models.payments import PaymentConfirmation
from hub20.apps.core.models.transfers import (
    BlockchainTransferExecution,
    RaidenTransferExecution,
    Transfer,
    TransferCancellation,
    TransferExecution,
    TransferFailure,
)
from hub20.apps.ethereum_money import get_ethereum_account_model
from hub20.apps.ethereum_money.models import EthereumToken
from hub20.apps.ethereum_money.signals import incoming_transfer_mined, outgoing_transfer_mined
from hub20.apps.raiden.models import Payment as RaidenPayment, Raiden
from hub20.apps.raiden.signals import service_deposit_sent

logger = logging.getLogger(__name__)
User = get_user_model()


EthereumAccount = get_ethereum_account_model()


@receiver(post_save, sender=User)
def on_user_created_create_account(sender, **kw):
    if kw["created"]:
        UserAccount.objects.get_or_create(user=kw["instance"])


@receiver(post_save, sender=Chain)
def on_chain_created_create_treasury(sender, **kw):
    if kw["created"]:
        Treasury.objects.get_or_create(chain=kw["instance"])


@receiver(post_save, sender=Raiden)
def on_raiden_created_create_account(sender, **kw):
    if kw["created"]:
        RaidenClientAccount.objects.get_or_create(raiden=kw["instance"])


@receiver(post_save, sender=BaseEthereumAccount)
@receiver(post_save, sender=Raiden)
@receiver(post_save, sender=EthereumAccount)
def on_wallet_created_create_account(sender, **kw):
    if kw["created"]:
        WalletAccount.objects.get_or_create(account=kw["instance"])


# In-Flows
@atomic()
@receiver(incoming_transfer_mined, sender=Transaction)
def on_incoming_transfer_mined_move_funds_from_external_address_to_wallet(sender, **kw):
    wallet = kw["account"]
    amount = kw["amount"]
    transaction = kw["transaction"]

    params = dict(reference=transaction, currency=amount.currency, amount=amount.amount)
    external_address_account, _ = ExternalAddressAccount.objects.get_or_create(
        address=transaction.from_address
    )

    external_address_book = external_address_account.get_book(token=amount.currency)
    wallet_book = wallet.onchain_account.get_book(token=amount.currency)

    external_address_book.debits.create(**params)
    wallet_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=RaidenPayment)
def on_raiden_payment_received_move_funds_from_external_address_to_raiden(sender, **kw):
    if kw["created"]:
        payment = kw["instance"]
        raiden = payment.channel.raiden

        is_received = payment.receiver_address == raiden.address

        if is_received:
            params = dict(reference=payment, currency=payment.token, amount=payment.amount)

            external_address_account, _ = ExternalAddressAccount.objects.get_or_create(
                address=payment.sender_address
            )

            external_account_book = external_address_account.get_book(token=payment.token)
            raiden_book = raiden.raiden_account.get_book(token=payment.token)

            external_account_book.debits.create(**params)
            raiden_book.credits.create(**params)


# Out-flows
@atomic()
@receiver(outgoing_transfer_mined, sender=Transaction)
def on_outgoing_transfer_mined_move_funds_from_wallet_to_external_address(sender, **kw):
    transaction = kw["transaction"]
    amount = kw["amount"]
    wallet = kw["account"]
    address = kw["address"]

    params = dict(reference=transaction, currency=amount.currency, amount=amount.amount)
    external_account, _ = ExternalAddressAccount.objects.get_or_create(address=address)

    wallet_book = wallet.onchain_account.get_book(token=amount.currency)
    external_account_book = external_account.get_book(token=amount.currency)

    wallet_book.debits.create(**params)
    external_account_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=RaidenTransferExecution)
def on_raiden_transfer_executed_move_funds_from_raiden_to_external_address(sender, **kw):
    if kw["created"]:
        execution = kw["instance"]
        transfer = execution.transfer

        payment = execution.raidentransferexecution.payment
        params = dict(reference=transfer, currency=transfer.currency, amount=transfer.amount)

        external_account, _ = ExternalAddressAccount.objects.get_or_create(
            address=transfer.address
        )

        external_account_book = external_account.get_book(token=transfer.currency)
        raiden_book = payment.channel.raiden.raiden_account.get_book(token=transfer.currency)

        raiden_book.debits.create(**params)
        external_account_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=BlockchainTransferExecution)
def on_blockchain_transfer_executed_move_fee_from_sender_to_treasury(sender, **kw):
    if kw["created"]:
        execution = kw["instance"]
        transaction = execution.transaction

        fee = execution.fee
        ETH = execution.fee.currency

        treasury_book = transaction.block.chain.treasury.get_book(token=ETH)
        sender_book = execution.transfer.sender.account.get_book(token=ETH)

        params = dict(reference=transaction, currency=ETH, amount=fee.amount)

        sender_book.debits.create(**params)
        treasury_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=Transaction)
def on_transaction_submitted_move_fee_from_wallet_to_fee_account(sender, **kw):
    if kw["created"]:
        transaction = kw["instance"]

        wallet = BaseEthereumAccount.objects.filter(address=transaction.from_address).first()
        if not wallet:
            return

        ETH = EthereumToken.ETH(chain=transaction.block.chain)
        fee = ETH.from_wei(transaction.gas_fee)
        fee_account = ExternalAddressAccount.get_transaction_fee_account()

        wallet_book = wallet.onchain_account.get_book(token=ETH)
        fee_book = fee_account.get_book(token=ETH)

        params = dict(reference=transaction, currency=ETH, amount=fee.amount)

        wallet_book.debits.create(**params)
        fee_book.credits.create(**params)


# Internal movements
@atomic()
@receiver(post_save, sender=Transfer)
def on_transfer_created_move_funds_from_sender_to_treasury(sender, **kw):
    if kw["created"]:
        transfer = kw["instance"]
        params = dict(reference=transfer, currency=transfer.currency, amount=transfer.amount)

        user_book = transfer.sender.account.get_book(token=transfer.currency)
        treasury_book = transfer.currency.chain.treasury.get_book(token=transfer.currency)

        user_book.debits.create(**params)
        treasury_book.credits.create(**params)


@atomic()
@receiver(post_save, sender=TransferExecution)
def on_internal_transfer_executed_move_funds_from_treasury_to_receiver(sender, **kw):
    if kw["created"]:
        execution = kw["instance"]
        transfer = execution.transfer

        if not transfer.receiver:
            logger.warning("Expected Internal Transfer, but no receiver user defined")
            return

        params = dict(reference=transfer, currency=transfer.currency, amount=transfer.amount)

        treasury_book = transfer.currency.chain.treasury.get_book(token=transfer.currency)
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
            treasury_book = payment.currency.chain.treasury.get_book(token=payment.currency)
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
            treasury_book = transfer.currency.chain.treasury.get_book(token=transfer.currency)
            sender_book = transfer.sender.account.get_book(token=transfer.currency)
            treasury_book.debits.create(
                reference=transfer_action, currency=transfer.currency, amount=transfer.amount
            )
            sender_book.credits.create(
                reference=transfer_action, currency=transfer.currency, amount=transfer.amount
            )

        except Exception as exc:
            logger.exception(exc)


@receiver(service_deposit_sent, sender=Transaction)
def on_service_deposit_transaction_move_funds_from_raiden_wallet_to_external_account(sender, **kw):
    deposit = kw["amount"]
    transaction = kw["transaction"]
    udc_address = kw["contract_address"]
    raiden = kw["raiden"]

    token = deposit.currency

    params = dict(reference=transaction, currency=token, amount=deposit.amount)

    external_account, _ = ExternalAddressAccount.objects.get_or_create(address=udc_address)
    raiden_wallet_account, _ = WalletAccount.objects.get_or_create(account=raiden)

    external_account_book = external_account.get_book(token=token)
    raiden_book = raiden_wallet_account.get_book(token=token)

    raiden_book.debits.create(**params)
    external_account_book.credits.create(**params)


__all__ = [
    "on_user_created_create_account",
    "on_chain_created_create_treasury",
    "on_raiden_created_create_account",
    "on_wallet_created_create_account",
    "on_incoming_transfer_mined_move_funds_from_external_address_to_wallet",
    "on_raiden_payment_received_move_funds_from_external_address_to_raiden",
    "on_outgoing_transfer_mined_move_funds_from_wallet_to_external_address",
    "on_raiden_transfer_executed_move_funds_from_raiden_to_external_address",
    "on_blockchain_transfer_executed_move_fee_from_sender_to_treasury",
    "on_transaction_submitted_move_fee_from_wallet_to_fee_account",
    "on_transfer_created_move_funds_from_sender_to_treasury",
    "on_internal_transfer_executed_move_funds_from_treasury_to_receiver",
    "on_payment_confirmed_move_funds_from_treasury_to_payee",
    "on_reverted_transaction_move_funds_from_treasury_to_sender",
    "on_service_deposit_transaction_move_funds_from_raiden_wallet_to_external_account",
]
