import logging

import celery_pubsub
from celery import shared_task
from raiden_contracts.constants import CONTRACT_TOKEN_NETWORK
from raiden_contracts.contract_manager import ContractManager, contracts_precompiled_path
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.client import BLOCK_CREATION_INTERVAL, make_web3
from hub20.apps.blockchain.models import (
    EventIndexer,
    Transaction,
    TransactionDataRecord,
    Web3Provider,
)
from hub20.apps.blockchain.tasks import stream_processor_lock
from hub20.apps.ethereum_money.client import get_account_balance
from hub20.apps.ethereum_money.models import EthereumToken, EthereumTokenAmount
from hub20.apps.ethereum_money.typing import TokenAmount_T
from hub20.apps.raiden import models
from hub20.apps.raiden.client import (
    RaidenClient,
    get_service_deposit_balance,
    get_service_token,
    get_service_total_deposit,
)
from hub20.apps.raiden.exceptions import InsufficientBalanceError, RaidenConnectionError
from hub20.apps.raiden.models import Channel, Raiden, TokenNetwork

RAIDEN_CONTRACTS_MANAGER = ContractManager(contracts_precompiled_path())
TOKEN_NETWORK_CONTRACT_ABI = RAIDEN_CONTRACTS_MANAGER.get_contract_abi(CONTRACT_TOKEN_NETWORK)


logger = logging.getLogger(__name__)


@shared_task(bind=True)
def index_channel_open_events(self):
    indexer_name = "raiden:opened_token_network_channels"

    for provider in Web3Provider.available.filter(chain__tokens__tokennetwork__isnull=False):
        event_indexer = EventIndexer.make(provider.chain_id, indexer_name)
        w3 = make_web3(provider=provider)
        contract = w3.eth.contract(abi=TOKEN_NETWORK_CONTRACT_ABI)

        current_block = w3.eth.block_number
        abi = contract.events.ChannelOpened._get_event_abi()

        # The more the indexer is behind, the more time it will have to keep the lock
        lock_ttl = max(BLOCK_CREATION_INTERVAL, current_block - event_indexer.last_block)

        with stream_processor_lock(provider, self.app.oid, lock_ttl) as acquired:
            if acquired:
                while event_indexer.last_block <= current_block:
                    from_block = event_indexer.last_block
                    to_block = min(current_block, from_block + BLOCK_SCAN_RANGE)

                    logger.debug(
                        f"Getting {indexer_name} events between {from_block} and {to_block}"
                    )
                    _, event_filter_params = construct_event_filter_params(
                        abi, w3.codec, fromBlock=from_block, toBlock=to_block
                    )

                    for log in w3.eth.get_logs(event_filter_params):
                        event_data = get_event_data(w3.codec, abi, log)
                        celery_pubsub.publish(
                            "blockchain.event.token_network_channel_opened.mined",
                            chain_id=w3.eth.chain_id,
                            event_data=event_data,
                            provider_url=provider.url,
                        )

                event_indexer.last_block = to_block
                event_indexer.save()


@shared_task(bind=True)
def index_channel_close_events(self):
    indexer_name = "raiden:closed_token_network_channels"

    for provider in Web3Provider.available.filter(chain__tokens__tokennetwork__isnull=False):
        event_indexer = EventIndexer.make(provider.chain_id, indexer_name)
        w3 = make_web3(provider=provider)
        contract = w3.eth.contract(abi=TOKEN_NETWORK_CONTRACT_ABI)

        current_block = w3.eth.block_number
        abi = contract.events.ChannelClosed._get_event_abi()

        lock_ttl = max(BLOCK_CREATION_INTERVAL, current_block - event_indexer.last_block)

        with stream_processor_lock(provider, self.app.oid, lock_ttl) as acquired:
            if acquired:
                while event_indexer.last_block <= current_block:
                    from_block = event_indexer.last_block
                    to_block = min(current_block, from_block + BLOCK_SCAN_RANGE)

                    logger.debug(
                        f"Getting {indexer_name} events between {from_block} and {to_block}"
                    )
                    _, event_filter_params = construct_event_filter_params(
                        abi, w3.codec, fromBlock=from_block, toBlock=to_block
                    )

                    for log in w3.eth.get_logs(event_filter_params):
                        event_data = get_event_data(w3.codec, abi, log)
                        celery_pubsub.publish(
                            "blockchain.event.token_network_channel_closed.mined",
                            chain_id=w3.eth.chain_id,
                            event_data=event_data,
                            provider_url=provider.url,
                        )

                event_indexer.last_block = to_block
                event_indexer.save()


@shared_task
def sync_channels():
    for raiden_client in [RaidenClient(raiden_node=raiden) for raiden in Raiden.objects.all()]:
        try:
            logger.debug(f"Running channel sync for {raiden_client.raiden.url}")
            raiden_client.get_channels()
        except RaidenConnectionError as exc:
            logger.error(f"Failed to connect to raiden node: {exc}")
        except Exception as exc:
            logger.exception(f"Error on channel sync: {exc}")


@shared_task
def sync_payments():
    for raiden_client in [RaidenClient(raiden_node=raiden) for raiden in Raiden.objects.all()]:
        try:
            logger.debug(f"Running payment sync for {raiden_client.raiden.url}")
            raiden_client.get_new_payments()
        except RaidenConnectionError as exc:
            logger.error(f"Failed to connect to raiden node: {exc}")
        except Exception as exc:
            logger.exception(f"Error on payment sync: {exc}")


@shared_task
def check_udc_balances(chain_id, block_data, provider_url):
    try:

        sender_addresses = [t["from"] for t in block_data["transactions"]]
        recipient_addresses = [t["to"] for t in block_data["transactions"]]

        tx_addresses = set(sender_addresses + recipient_addresses)

        raidens = Raiden.objects.filter(chain_id=chain_id, account__address__in=tx_addresses)

        if raidens.exists():
            provider = Web3Provider.available.get(url=provider_url, chain_id=chain_id)
            w3 = make_web3(provider=provider)
            service_token = get_service_token(w3=w3)
            for raiden in raidens:
                total_deposit = get_service_total_deposit(w3=w3, raiden=raiden)
                balance = get_service_deposit_balance(w3=w3, raiden=raiden)
                udc, _ = models.UserDeposit.objects.update_or_create(
                    raiden=raiden,
                    defaults={
                        "token": service_token,
                        "total_deposit": total_deposit.amount,
                        "balance": balance.amount,
                    },
                )

    except Web3Provider.DoesNotExist:
        logger.info(f"Could not find a provider for Chain #{chain_id}")


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


@shared_task(
    bind=True, name="channel_deposit", ignore_result=False, throws=(InsufficientBalanceError,)
)
def make_channel_deposit(self, channel_id, deposit_amount: TokenAmount_T):

    channel = Channel.objects.get(id=channel_id)

    w3 = make_web3(provider=channel.raiden.chain.provider)

    raiden_client = RaidenClient(raiden_node=channel.raiden)
    token_amount = EthereumTokenAmount(currency=channel.token, amount=deposit_amount)

    chain_balance = get_account_balance(w3=w3, token=channel.token, address=channel.raiden.address)

    if chain_balance < token_amount:
        raise InsufficientBalanceError(
            f"Insufficient balance {chain_balance.formatted} to deposit on channel"
        )

    return raiden_client.make_channel_deposit(channel, token_amount)


@shared_task(
    bind=True,
    name="channel_withdraw",
    ignore_result=False,
    track_started=True,
    throws=(InsufficientBalanceError,),
)
def make_channel_withdraw(self, channel_id, deposit_amount: TokenAmount_T):
    channel = Channel.objects.get(id=channel_id)
    raiden_client = RaidenClient(raiden_node=channel.raiden)
    token_amount = EthereumTokenAmount(currency=channel.token, amount=deposit_amount)
    channel_balance = channel.balance_amount

    if channel_balance < token_amount:
        raise InsufficientBalanceError(f"Channel has only {channel_balance.formatted} to withdraw")

    return raiden_client.make_channel_withdraw(channel, token_amount)


@shared_task(
    bind=True,
    name="join_token_network",
    ignore_result=False,
    track_started=True,
    throws=(InsufficientBalanceError,),
)
def join_token_network(self, raiden_url, token_address, deposit_amount: TokenAmount_T):
    raiden = Raiden.objects.get(url=raiden_url)
    token = EthereumToken.objects.get(address=token_address, chain_id=raiden.chain_id)
    token_network = TokenNetwork.objects.get(token__address=token_address)

    raiden_client = RaidenClient(raiden_node=raiden)
    token_amount = EthereumTokenAmount(currency=token, amount=deposit_amount)

    w3 = make_web3(provider=raiden.chain.provider)
    chain_balance = get_account_balance(w3=w3, token=token, address=raiden.address)

    if chain_balance < token_amount:
        raise InsufficientBalanceError(
            f"Balance {chain_balance.formatted} less than requested to join token network"
        )

    return raiden_client.join_token_network(token_network=token_network, amount=token_amount)


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
celery_pubsub.subscribe("blockchain.mined.block", check_udc_balances)
