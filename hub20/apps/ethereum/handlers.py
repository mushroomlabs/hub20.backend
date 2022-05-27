import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.db.transaction import atomic
from django.dispatch import receiver

from hub20.apps.core.models import get_treasury_account
from hub20.apps.core.models.payments import Deposit, PaymentConfirmation
from hub20.apps.core.models.stores import Checkout
from hub20.apps.core.settings import app_settings
from hub20.apps.core.signals import payment_received
from hub20.apps.core.tasks import (
    call_checkout_webhook,
    notify_block_created,
    publish_checkout_event,
    send_session_event,
)

from . import signals
from .constants import Events
from .models import (
    Block,
    BlockchainPayment,
    BlockchainPaymentNetwork,
    BlockchainPaymentRoute,
    BlockchainTransfer,
    BlockchainTransferConfirmation,
    Chain,
    ChainMetadata,
    Transaction,
    TransactionDataRecord,
)

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Chain)
def on_chain_created_register_payment_network(sender, **kw):
    chain = kw["instance"]
    if kw["created"]:
        BlockchainPaymentNetwork.objects.update_or_create(
            chain=chain, defaults={"name": chain.name}
        )


@receiver(post_save, sender=Chain)
def on_chain_created_create_metadata_entry(sender, **kw):
    if kw["created"]:
        ChainMetadata.objects.get_or_create(chain=kw["instance"])


def _check_for_blockchain_payment_confirmations(block_number):
    confirmed_block = block_number - app_settings.Payment.minimum_confirmations

    unconfirmed_payments = BlockchainPayment.objects.filter(
        confirmation__isnull=True, transaction__block__number__lte=confirmed_block
    )

    for payment in unconfirmed_payments:
        PaymentConfirmation.objects.create(payment=payment)


def _publish_block_created_event(chain_id, block_data):
    block_number = block_data.get("number")
    routes = BlockchainPaymentRoute.objects.in_chain(chain_id).open(block_number=block_number)

    notify_block_created.delay(chain_id, block_data)

    for checkout in Checkout.objects.filter(order__routes__in=routes):
        logger.debug(
            f"Scheduling publish event for checkout {checkout.id}: block #{block_number} created"
        )
        publish_checkout_event.delay(
            checkout.id,
            event=Events.BLOCK_CREATED.value,
            block=block_number,
            chain_id=chain_id,
        )


@receiver(post_save, sender=Chain)
def on_chain_updated_check_payment_confirmations(sender, **kw):
    chain = kw["instance"]
    _check_for_blockchain_payment_confirmations(chain.highest_block)


@receiver(payment_received, sender=BlockchainPayment)
def on_blockchain_payment_received_send_notification(sender, **kw):
    payment = kw["payment"]

    deposit = Deposit.objects.filter(routes__payments=payment).first()

    checkout = Checkout.objects.filter(order__routes__payments=payment).first()

    payment_data = dict(
        amount=str(payment.amount),
        token=payment.currency.address,
        transaction=payment.transaction.hash.hex(),
        block_number=payment.transaction.block.number,
    )

    if deposit and deposit.session_key:
        send_session_event.delay(
            session_key=deposit.session_key,
            event=Events.DEPOSIT_RECEIVED.value,
            deposit_id=str(payment.route.deposit.id),
            **payment_data,
        )

    if checkout:
        publish_checkout_event.delay(
            checkout.id, event=Events.DEPOSIT_RECEIVED.value, **payment_data
        )


@receiver(payment_received, sender=BlockchainPayment)
def on_blockchain_payment_received_call_checkout_webhooks(sender, **kw):
    payment = kw["payment"]

    checkouts = Checkout.objects.filter(order__routes__payments=payment)
    for checkout_id in checkouts.values_list("id", flat=True):
        call_checkout_webhook.delay(checkout_id)


@receiver(signals.incoming_transfer_mined, sender=Transaction)
def on_incoming_transfer_mined_check_blockchain_payments(sender, **kw):
    account = kw["account"]
    amount = kw["amount"]
    transaction = kw["transaction"]

    if BlockchainPayment.objects.filter(transaction=transaction).exists():
        logger.info(f"Transaction {transaction} is already recorded for payment")
        return

    route = BlockchainPaymentRoute.objects.filter(
        deposit__currency=amount.currency,
        account=account,
        payment_window__contains=transaction.block.number,
    ).first()

    if not route:
        return

    payment = BlockchainPayment.objects.create(
        route=route,
        amount=amount.amount,
        currency=amount.currency,
        transaction=transaction,
    )
    payment_received.send(sender=BlockchainPayment, payment=payment)


@receiver(signals.incoming_transfer_broadcast, sender=TransactionDataRecord)
def on_incoming_transfer_broadcast_send_notification_to_active_sessions(sender, **kw):
    recipient = kw["account"]
    payment_amount = kw["amount"]
    tx_data = kw["transaction_data"]

    route = BlockchainPaymentRoute.objects.open().filter(account=recipient).first()

    if not route:
        return

    if route.deposit.session_key:
        send_session_event.delay(
            route.deposit.session_key,
            event=Events.DEPOSIT_BROADCAST.value,
            deposit_id=str(route.deposit.id),
            amount=str(payment_amount.amount),
            token=payment_amount.currency.address,
            transaction=tx_data.hash.hex(),
        )


@receiver(signals.incoming_transfer_broadcast, sender=TransactionDataRecord)
def on_incoming_transfer_broadcast_send_notification_to_open_checkouts(sender, **kw):
    recipient = kw["account"]
    payment_amount = kw["amount"]
    tx_data = kw["transaction_data"]

    route = BlockchainPaymentRoute.objects.open().filter(account=recipient).first()

    if not route:
        return

    checkout = Checkout.objects.filter(order__routes=route).first()

    if checkout:
        publish_checkout_event.delay(
            checkout.id,
            event=Events.DEPOSIT_BROADCAST.value,
            amount=str(payment_amount.amount),
            token=payment_amount.currency.address,
            transaction=tx_data.hash.hex(),
        )


@receiver(signals.block_sealed, sender=Block)
def on_block_sealed_publish_block_created_event(sender, **kw):
    block_data = kw["block_data"]
    chain_id = kw["chain_id"]
    logger.debug(f"Handling block sealed notification of new block on chain #{chain_id}")
    _publish_block_created_event(chain_id=chain_id, block_data=block_data)


@receiver(signals.block_sealed, sender=Block)
def on_block_sealed_check_confirmed_payments(sender, **kw):
    block_data = kw["block_data"]
    _check_for_blockchain_payment_confirmations(block_data.get("number"))


@receiver(post_save, sender=Block)
def on_block_created_check_confirmed_payments(sender, **kw):
    if kw["created"]:
        block = kw["instance"]
        _check_for_blockchain_payment_confirmations(block.number)


@receiver(signals.block_sealed, sender=Block)
def on_block_added_publish_expired_blockchain_routes(sender, **kw):
    block_data = kw["block_data"]
    block_number = block_data["number"]

    expiring_routes = BlockchainPaymentRoute.objects.filter(
        payment_window__endswith=block_number - 1
    )

    for route in expiring_routes:
        publish_checkout_event.delay(
            route.deposit_id,
            event=Events.ROUTE_EXPIRED.value,
            route=route.account.address,
        )


@receiver(signals.outgoing_transfer_mined, sender=Transaction)
def on_blockchain_transfer_mined_record_confirmation(sender, **kw):
    amount = kw["amount"]
    transaction = kw["transaction"]
    address = kw["address"]

    transfer = BlockchainTransfer.processed.filter(
        amount=amount.amount,
        currency=amount.currency,
        address=address,
        receipt__blockchaintransferreceipt__transaction_data__hash=transaction.hash,
    ).first()

    if transfer:
        BlockchainTransferConfirmation.objects.create(transfer=transfer, transaction=transaction)


# Accounting
@atomic()
@receiver(signals.incoming_transfer_mined, sender=Transaction)
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
    blockchain_account = transaction.chain.blockchainpaymentnetwork.account
    treasury = get_treasury_account()

    blockchain_book = blockchain_account.get_book(token=amount.currency)
    treasury_book = treasury.get_book(token=amount.currency)

    blockchain_book.debits.get_or_create(**params)
    treasury_book.credits.get_or_create(**params)


@atomic()
@receiver(signals.outgoing_transfer_mined, sender=Transaction)
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
    blockchain_account = transaction.chain.blockchainpaymentnetwork.account
    treasury = get_treasury_account()

    treasury_book = treasury.get_book(token=amount.currency)
    blockchain_book = blockchain_account.get_book(token=amount.currency)

    treasury_book.debits.get_or_create(**params)
    blockchain_book.credits.get_or_create(**params)


@atomic()
@receiver(post_save, sender=BlockchainTransferConfirmation)
def on_blockchain_transfer_confirmed_move_funds_from_treasury_to_blockchain(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        transaction = confirmation.transaction
        transfer = confirmation.transfer

        treasury = get_treasury_account()
        blockchain_account = transaction.chain.blockchainpaymentnetwork.account

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
@receiver(post_save, sender=BlockchainTransferConfirmation)
def on_blockchain_transfer_confirmed_move_fee_from_sender_to_blockchain(sender, **kw):
    if kw["created"]:
        confirmation = kw["instance"]
        transaction = confirmation.transaction

        fee = confirmation.fee
        native_token = confirmation.fee.currency

        treasury = get_treasury_account()
        blockchain_account = transaction.chain.blockchainpaymentnetwork.account

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
        # as we might add the case where the hub operator pays for transfers.

        sender_book.debits.get_or_create(**params)
        treasury_book.credits.get_or_create(**params)

        treasury_book.debits.get_or_create(**params)
        blockchain_book.credits.get_or_create(**params)


__all__ = [
    "on_chain_created_register_payment_network",
    "on_chain_created_create_metadata_entry",
    "on_chain_updated_check_payment_confirmations",
    "on_blockchain_payment_received_send_notification",
    "on_incoming_transfer_mined_check_blockchain_payments",
    "on_incoming_transfer_broadcast_send_notification_to_active_sessions",
    "on_incoming_transfer_broadcast_send_notification_to_open_checkouts",
    "on_block_sealed_publish_block_created_event",
    "on_block_sealed_check_confirmed_payments",
    "on_block_created_check_confirmed_payments",
    "on_block_added_publish_expired_blockchain_routes",
    "on_blockchain_transfer_mined_record_confirmation",
    "on_incoming_transfer_mined_move_funds_from_blockchain_to_treasury",
    "on_outgoing_transfer_mined_move_funds_from_treasury_to_blockchain",
    "on_blockchain_transfer_confirmed_move_funds_from_treasury_to_blockchain",
    "on_blockchain_transfer_confirmed_move_fee_from_sender_to_blockchain",
]
