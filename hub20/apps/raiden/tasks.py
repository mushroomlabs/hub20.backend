import logging

import celery_pubsub
from celery import shared_task
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import Transaction, TransactionDataRecord, Web3Provider
from hub20.apps.ethereum_money.client import get_account_balance
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.ethereum_money.typing import TokenAmount_T
from hub20.apps.raiden import models
from hub20.apps.raiden.client import RaidenClient, get_service_token, get_service_total_deposit
from hub20.apps.raiden.exceptions import InsufficientBalanceError
from hub20.apps.raiden.models import Raiden

logger = logging.getLogger(__name__)


@shared_task
def check_token_network_channel_events(chain_id, event_data, provider_url):
    token_network = models.TokenNetwork.objects.filter(address=event_data.address).first()

    if not token_network:
        return

    participants = (event_data.args.participant1, event_data.args.participant2)
    channel_identifier = event_data.args.channel_identifier
    channel, _ = token_network.channels.get_or_create(
        identifier=channel_identifier, participant_addresses=participants
    )

    try:
        provider = Web3Provider.objects.get(url=provider_url)
        w3 = make_web3(provider=provider)
        tx_hash = event_data.transactionHash

        tx_data = w3.eth.get_transaction(tx_hash)
        TransactionDataRecord.make(chain_id=chain_id, tx_data=tx_data)
        block_data = w3.eth.get_block(tx_data.blockHash)
        tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
        tx = Transaction.make(chain_id=chain_id, block_data=block_data, tx_receipt=tx_receipt)

        token_network.events.get_or_create(channel=channel, transaction=tx, name=event_data.event)
    except TransactionNotFound:
        logger.warning(f"Failed to get information for Tx {event_data.transactionHash.hex()}")


@shared_task(
    bind=True, name="udc_deposit", ignore_result=False, throws=(InsufficientBalanceError,)
)
def make_udc_deposit(self, raiden_url: str, amount: TokenAmount_T):
    raiden = Raiden.objects.get(url=raiden_url)
    raiden_client = RaidenClient(raiden_node=raiden)
    w3 = make_web3(provider=raiden.chain.provider)
    service_token = get_service_token(w3=w3)

    onchain_balance = get_account_balance(w3=w3, token=service_token, address=raiden.address)
    deposit_token_amount = EthereumTokenAmount(currency=service_token, amount=amount)

    if onchain_balance < deposit_token_amount:
        raise InsufficientBalanceError(f"On chain balance for {raiden.address} is not enough")

    current_deposit = get_service_total_deposit(w3=w3, raiden=raiden)
    new_total_deposit = current_deposit + deposit_token_amount

    return raiden_client.make_user_deposit(total_deposit_amount=new_total_deposit)


@shared_task
def make_channel_deposit(order_id: int):
    order = models.ChannelDepositOrder.objects.filter(id=order_id).first()

    if not order:
        logger.warning(f"Channel Deposit Order {order_id} not found")
        return

    w3 = make_web3(provider=order.channel.token.chain.provider)

    client = RaidenClient(raiden_node=order.raiden)
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

    client = RaidenClient(raiden_node=order.raiden)
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

    client = RaidenClient(raiden_node=order.raiden)
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

    client = RaidenClient(raiden_node=order.raiden)
    client.leave_token_network(token_network=order.token_network)


celery_pubsub.subscribe(
    "blockchain.event.token_network_channel_opened.mined", check_token_network_channel_events
)
celery_pubsub.subscribe(
    "blockchain.event.token_network_channel_closed.mined", check_token_network_channel_events
)
