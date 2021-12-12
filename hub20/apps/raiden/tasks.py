import logging

import celery_pubsub
from celery import shared_task

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import Transaction
from hub20.apps.ethereum_money.client import get_account_balance
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.raiden import models
from hub20.apps.raiden.client.blockchain import get_token_network_contract, make_service_deposit
from hub20.apps.raiden.client.node import RaidenClient
from hub20.apps.raiden.exceptions import InsufficientBalanceError

logger = logging.getLogger(__name__)


@shared_task
def check_token_network_channel_events(
    chain_id, block_data, transaction_data, transaction_receipt
):
    try:
        token_network = models.TokenNetwork.objects.get(address=transaction_receipt["to"])
        w3 = make_web3(provider=token_network.token.chain.provider)
        contract = get_token_network_contract(w3=w3, token_network=token_network)

        channel_opened_events = contract.events.ChannelOpened().processReceipt(transaction_receipt)
        channel_closed_events = contract.events.ChannelOpened().processReceipt(transaction_receipt)

        channel_events = list(channel_opened_events) + list(channel_closed_events)

        if not channel_events:
            return

        tx = Transaction.make(
            chain_id=chain_id,
            block_data=block_data,
            tx_receipt=transaction_receipt,
            tx_data=transaction_data,
        )
        for event in channel_events:
            participants = (event.args.participant1, event.args.participant2)
            channel_identifier = event.args.channel_identifier
            channel, _ = token_network.channels.get_or_create(
                identifier=channel_identifier, participant_addresses=participants
            )

            token_network.events.get_or_create(channel=channel, transaction=tx, name=event.event)
    except models.TokenNetwork.DoesNotExist:
        return


@shared_task
def check_order_results(chain_id, block_data, transaction_data, transaction_receipt):
    open_order = models.RaidenManagementOrder.objects.filter(
        result__transaction__isnull=True, transaction_hash=transaction_receipt.transactionHash
    ).first()

    if not open_order:
        return

    tx = Transaction.make(
        chain_id=chain_id,
        block_data=block_data,
        tx_data=transaction_data,
        tx_receipt=transaction_receipt,
    )

    successful = bool(transaction_receipt.status)

    model_class = (
        models.RaidenManagerOrderResult if successful else models.RaidenManagementOrderError
    )

    return model_class.objects.create(order=open_order, transaction=tx)


@shared_task
def make_udc_deposit(order_id: int):
    order = models.UserDepositContractOrder.objects.filter(id=order_id).first()

    if not order:
        logging.warning(f"UDC Order {order_id} not found")
        return

    w3 = make_web3(provider=order.currency.chain.provider)
    token_amount = order.as_token_amount

    try:
        make_service_deposit(w3=w3, account=order.raiden, amount=token_amount)
    except InsufficientBalanceError as exc:
        return models.RaidenManagementOrderError.objects.create(order=order, message=str(exc))


@shared_task
def make_channel_deposit(order_id: int):
    order = models.ChannelDepositOrder.objects.filter(id=order_id).first()

    if not order:
        logger.warning(f"Channel Deposit Order {order_id} not found")
        return

    w3 = make_web3(provider=order.channel.token.chain.provider)

    client = RaidenClient(raiden_account=order.raiden)
    token_amount = EthereumTokenAmount(currency=order.channel.token, amount=order.amount)

    chain_balance = get_account_balance(
        w3=w3, token=order.channel.token, address=order.raiden.address
    )

    if chain_balance < token_amount:
        logger.warning(f"Insufficient balance {chain_balance.formatted} to deposit on channel")
        return

    client.make_channel_deposit(order.channel, token_amount)


@shared_task
def make_channel_withdraw(order_id: int):
    order = models.ChannelWithdrawOrder.objects.filter(id=order_id).first()

    if not order:
        logger.warning(f"Channel Withdraw Order {order_id} not found")
        return

    client = RaidenClient(raiden_account=order.raiden)
    token_amount = EthereumTokenAmount(currency=order.channel.token, amount=order.amount)
    channel_balance = order.channel.balance_amount

    if channel_balance < token_amount:
        logger.warning(f"Insufficient balance {channel_balance.formatted} to withdraw")
        return

    client.make_channel_withdraw(order.channel, token_amount)


@shared_task
def join_token_network(order_id: int):
    order = models.JoinTokenNetworkOrder.objects.filter(id=order_id).first()

    if not order:
        logger.warning(f"Join Token Network Order {order_id} not found")

    client = RaidenClient(raiden_account=order.raiden)
    token_amount = EthereumTokenAmount(currency=order.token_network.token, amount=order.amount)

    w3 = make_web3(provider=order.token_network.token.chain.provider)

    chain_balance = get_account_balance(
        w3=w3, token=order.token_network.token, address=order.raiden.address
    )

    if chain_balance < token_amount:
        logger.warning(
            f"Balance {chain_balance.formatted} smaller than request to join token network"
        )
        return

    client.join_token_network(token_network=order.token_network, amount=token_amount)


@shared_task
def leave_token_network(order_id: int):
    order = models.LeaveTokenNetworkOrder.objects.filter(id=order_id).first()

    if not order:
        logger.warning(f"Leave Token Network Order {order_id} not found")
        return

    client = RaidenClient(raiden_account=order.raiden)
    client.leave_token_network(token_network=order.token_network)


celery_pubsub.subscribe("blockchain.mined.transaction", check_token_network_channel_events)
celery_pubsub.subscribe("blockchain.mined.transaction", check_order_results)
