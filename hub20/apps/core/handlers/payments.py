import logging
from typing import Optional

from django.contrib.sessions.models import Session
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from hub20.apps.blockchain.models import (
    BaseEthereumAccount,
    Block,
    Chain,
    Transaction,
    TransactionDataRecord,
)
from hub20.apps.blockchain.signals import block_sealed
from hub20.apps.core import tasks
from hub20.apps.core.choices import PAYMENT_NETWORKS
from hub20.apps.core.consumers import Events
from hub20.apps.core.models import (
    BlockchainPayment,
    BlockchainPaymentRoute,
    Checkout,
    Deposit,
    InternalPayment,
    Payment,
    PaymentConfirmation,
    PaymentOrder,
    RaidenPayment,
    RaidenPaymentRoute,
)
from hub20.apps.core.settings import app_settings
from hub20.apps.core.signals import payment_received
from hub20.apps.ethereum_money.signals import incoming_transfer_broadcast, incoming_transfer_mined
from hub20.apps.raiden.models import Payment as RaidenNodePayment, Raiden
from hub20.apps.raiden.signals import raiden_payment_received
from hub20.apps.wallet import get_wallet_model

logger = logging.getLogger(__name__)
Wallet = get_wallet_model()


def _get_user_id(session: Session) -> Optional[int]:
    try:
        return int(session.get_decoded()["_auth_user_id"])
    except (KeyError, ValueError, TypeError):
        return None


def _get_user_session_keys(user_id):
    now = timezone.now()
    sessions = Session.objects.filter(expire_date__gt=now)
    return [s.session_key for s in sessions if _get_user_id(s) == user_id]


def _check_for_blockchain_payment_confirmations(block_number):
    confirmed_block = block_number - app_settings.Payment.minimum_confirmations

    unconfirmed_payments = BlockchainPayment.objects.filter(
        confirmation__isnull=True, transaction__block__number__lte=confirmed_block
    )

    for payment in unconfirmed_payments:
        PaymentConfirmation.objects.create(payment=payment)


def _publish_block_created_event(chain_id, block_number):
    for checkout in Checkout.objects.with_blockchain_route(block_number):
        logger.debug(
            f"Scheduling publish event for checkout {checkout.id}: block #{block_number} created"
        )
        tasks.publish_checkout_event.delay(
            checkout.id,
            event=Events.BLOCKCHAIN_BLOCK_CREATED.value,
            block=block_number,
            chain_id=chain_id,
        )


@receiver(post_save, sender=Chain)
def on_chain_updated_check_payment_confirmations(sender, **kw):
    chain = kw["instance"]
    _check_for_blockchain_payment_confirmations(chain.highest_block)


@receiver(incoming_transfer_mined, sender=Transaction)
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


@receiver(incoming_transfer_broadcast, sender=TransactionDataRecord)
def on_incoming_transfer_broadcast_send_notification_to_active_sessions(sender, **kw):
    recipient = kw["account"]
    payment_amount = kw["amount"]
    tx_data = kw["transaction_data"]

    route = BlockchainPaymentRoute.objects.open().filter(account=recipient).first()

    if not route:
        return

    deposit = Deposit.objects.with_blockchain_route().filter(routes=route).first()

    if deposit and deposit.session_key:
        tasks.send_session_event.delay(
            deposit.session_key,
            event=Events.BLOCKCHAIN_DEPOSIT_BROADCAST.value,
            deposit_id=str(deposit.id),
            amount=str(payment_amount.amount),
            token=payment_amount.currency.address,
            transaction=tx_data.hash.hex(),
        )


@receiver(incoming_transfer_broadcast, sender=TransactionDataRecord)
def on_incoming_transfer_broadcast_send_notification_to_open_checkouts(sender, **kw):
    recipient = kw["account"]
    payment_amount = kw["amount"]
    tx_data = kw["transaction_data"]

    route = BlockchainPaymentRoute.objects.open().filter(account=recipient).first()

    if not route:
        return

    checkout = Checkout.objects.with_blockchain_route().filter(routes=route).first()

    if checkout:
        tasks.publish_checkout_event.delay(
            checkout.id,
            event=Events.BLOCKCHAIN_DEPOSIT_BROADCAST.value,
            amount=str(payment_amount.amount),
            token=payment_amount.currency.address,
            transaction=tx_data.hash.hex(),
        )


@receiver(raiden_payment_received, sender=RaidenNodePayment)
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


@receiver(post_save, sender=Deposit)
@receiver(post_save, sender=PaymentOrder)
@receiver(post_save, sender=Checkout)
def on_order_created_set_blockchain_route(sender, **kw):

    if not kw["created"]:
        return

    deposit = kw["instance"]
    chain = deposit.currency.chain
    chain.refresh_from_db()
    if chain.synced:
        payment_window = BlockchainPaymentRoute.calculate_payment_window(chain)

        busy_routes = BlockchainPaymentRoute.objects.open().filter(
            deposit__currency=deposit.currency
        )
        available_accounts = BaseEthereumAccount.objects.exclude(blockchain_routes__in=busy_routes)

        account = available_accounts.order_by("?").first() or Wallet.generate()

        BlockchainPaymentRoute.objects.create(
            account=account, deposit=deposit, chain=chain, payment_window=payment_window
        )
    else:
        logger.warning("Failed to create blockchain route. Chain data not synced")


@receiver(post_save, sender=Deposit)
@receiver(post_save, sender=PaymentOrder)
@receiver(post_save, sender=Checkout)
def on_order_created_set_raiden_route(sender, **kw):

    if not kw["created"]:
        return

    deposit = kw["instance"]
    raiden = Raiden.objects.first()

    if raiden and raiden.open_channels.filter(token_network__token=deposit.currency).exists():
        raiden.payment_routes.create(deposit=deposit)


@receiver(block_sealed, sender=Block)
def on_block_sealed_publish_block_created_event(sender, **kw):
    block_data = kw["block_data"]
    chain_id = kw["chain_id"]
    _publish_block_created_event(chain_id=chain_id, block_number=block_data.get("number"))


@receiver(block_sealed, sender=Block)
def on_block_sealed_check_confirmed_payments(sender, **kw):
    block_data = kw["block_data"]
    _check_for_blockchain_payment_confirmations(block_data.get("number"))


@receiver(post_save, sender=Block)
def on_block_created_check_confirmed_payments(sender, **kw):
    if kw["created"]:
        block = kw["instance"]
        _check_for_blockchain_payment_confirmations(block.number)


@receiver(post_save, sender=Block)
def on_block_added_publish_expired_blockchain_routes(sender, **kw):
    block = kw["instance"]

    expiring_routes = BlockchainPaymentRoute.objects.filter(
        payment_window__endswith=block.number - 1
    )

    for route in expiring_routes:
        tasks.publish_checkout_event.delay(
            route.deposit_id,
            event=Events.BLOCKCHAIN_ROUTE_EXPIRED.value,
            route=route.account.address,
        )


@receiver(payment_received, sender=BlockchainPayment)
def on_blockchain_payment_received_send_notification(sender, **kw):
    payment = kw["payment"]

    deposit = Deposit.objects.filter(routes__payment=payment).first()

    checkout = Checkout.objects.filter(routes__payment=payment).first()

    payment_data = dict(
        amount=str(payment.amount),
        token=payment.currency.address,
        transaction=payment.transaction.hash.hex(),
        block_number=payment.transaction.block.number,
    )

    if deposit and deposit.session_key:
        tasks.send_session_event.delay(
            session_key=deposit.session_key,
            event=Events.BLOCKCHAIN_DEPOSIT_RECEIVED.value,
            deposit_id=str(payment.route.deposit.id),
            **payment_data,
        )

    if checkout:
        tasks.publish_checkout_event.delay(
            checkout.id, event=Events.BLOCKCHAIN_DEPOSIT_RECEIVED.value, **payment_data
        )


@receiver(post_save, sender=RaidenPayment)
@receiver(post_save, sender=InternalPayment)
def on_off_chain_payment_create_confirmation(sender, **kw):
    if kw["created"]:
        PaymentConfirmation.objects.create(payment=kw["instance"])


@receiver(payment_received, sender=BlockchainPayment)
def on_blockchain_payment_received_call_checkout_webhooks(sender, **kw):
    pay = kw["payment"]

    for checkout_id in Checkout.objects.filter(routes__payment=pay).values_list("id", flat=True):
        tasks.call_checkout_webhook.delay(checkout_id)


@receiver(post_save, sender=PaymentConfirmation)
def on_payment_confirmed_call_checkout_webhooks(sender, **kw):
    confirmation = kw["instance"]

    checkouts = Checkout.objects.filter(routes__payment__confirmation=confirmation)
    for checkout_id in checkouts.values_list("id", flat=True):
        tasks.call_checkout_webhook.delay(checkout_id)


@receiver(post_save, sender=PaymentConfirmation)
def on_payment_confirmed_publish_checkout(sender, **kw):
    if not kw["created"]:
        return

    confirmation = kw["instance"]
    payment = Payment.objects.filter(id=confirmation.payment_id).select_subclasses().first()

    if not payment:
        return

    checkouts = Checkout.objects.filter(routes__payment=payment)
    checkout_id = checkouts.values_list("id", flat=True).first()

    if checkout_id is None:
        return

    payment_method = {
        InternalPayment: PAYMENT_NETWORKS.internal,
        BlockchainPayment: PAYMENT_NETWORKS.blockchain,
        RaidenPayment: PAYMENT_NETWORKS.raiden,
    }.get(type(payment))

    event = {
        InternalPayment: Events.INTERNAL_DEPOSIT_CONFIRMED,
        BlockchainPayment: Events.BLOCKCHAIN_DEPOSIT_CONFIRMED,
        RaidenPayment: Events.RAIDEN_DEPOSIT_CONFIRMED,
    }.get(type(payment))

    tasks.publish_checkout_event.delay(
        checkout_id,
        amount=str(payment.amount),
        token=payment.currency.address,
        event=event and event.value,
        payment_method=payment_method,
    )


__all__ = [
    "on_chain_updated_check_payment_confirmations",
    "on_incoming_transfer_mined_check_blockchain_payments",
    "on_incoming_transfer_broadcast_send_notification_to_active_sessions",
    "on_incoming_transfer_broadcast_send_notification_to_open_checkouts",
    "on_raiden_payment_received_check_raiden_payments",
    "on_order_created_set_blockchain_route",
    "on_order_created_set_raiden_route",
    "on_block_added_publish_expired_blockchain_routes",
    "on_block_created_check_confirmed_payments",
    "on_block_sealed_check_confirmed_payments",
    "on_blockchain_payment_received_send_notification",
    "on_blockchain_payment_received_call_checkout_webhooks",
    "on_off_chain_payment_create_confirmation",
    "on_payment_confirmed_call_checkout_webhooks",
    "on_payment_confirmed_publish_checkout",
]
