import logging

from celery import shared_task

from hub20.apps.blockchain.client import get_web3
from hub20.apps.ethereum_money.client import get_account_balance
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.raiden import models
from hub20.apps.raiden.client.blockchain import get_service_token, make_service_deposit
from hub20.apps.raiden.client.node import RaidenClient
from hub20.apps.raiden.exceptions import InsufficientBalanceError

logger = logging.getLogger(__name__)


@shared_task
def make_udc_deposit(order_id: int):
    order = models.UserDepositContractOrder.objects.filter(id=order_id).first()

    if not order:
        logging.warning(f"UDC Order {order_id} not found")
        return

    w3 = get_web3()
    service_token = get_service_token(w3=w3)
    service_token_amount = EthereumTokenAmount(currency=service_token, amount=order.amount)

    try:
        make_service_deposit(w3=w3, account=order.raiden, amount=service_token_amount)
    except InsufficientBalanceError as exc:
        return models.RaidenManagementOrderError.objects.create(order=order, message=str(exc))


@shared_task
def make_channel_deposit(order_id: int):
    order = models.ChannelDepositOrder.objects.filter(id=order_id).first()

    if not order:
        logger.warning(f"Channel Deposit Order {order_id} not found")
        return

    w3 = get_web3()

    client = RaidenClient(account=order.raiden)
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

    client = RaidenClient(account=order.raiden)
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

    client = RaidenClient(account=order.raiden)
    token_amount = EthereumTokenAmount(currency=order.token_network.token, amount=order.amount)

    w3 = get_web3()

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

    client = RaidenClient(account=order.raiden)
    client.leave_token_network(token_network=order.token_network)
