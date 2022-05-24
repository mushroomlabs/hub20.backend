import logging
from asyncio.exceptions import TimeoutError

import celery_pubsub
from celery import shared_task
from django.core.cache import cache
from django.db.models import Q
from django.db.transaction import atomic
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params
from web3.exceptions import ExtraDataLengthError, LogTopicError, TransactionNotFound
from websockets.exceptions import InvalidStatusCode

from hub20.apps.core.abi.tokens import EIP20_ABI
from hub20.apps.core.models.accounts import BaseWallet
from hub20.apps.core.models.blockchain import (
    Block,
    Chain,
    EventIndexer,
    Transaction,
    TransactionDataRecord,
)
from hub20.apps.core.models.tokens import Token
from hub20.apps.core.models.wallets import Wallet, WalletBalanceRecord
from hub20.apps.core.tasks import broadcast_event, stream_processor_lock

from . import signals
from .analytics import MAX_PRIORITY_FEE_TRACKER, get_historical_block_data
from .app_settings import BLOCK_SCAN_RANGE
from .client import BLOCK_CREATION_INTERVAL, inspect_web3, make_web3
from .constants import Events
from .models import BlockchainPaymentRoute, TransferEvent, Web3Provider

logger = logging.getLogger(__name__)


# Tasks that are processing event logs from the blockchain (should
# have only one at a time)
@shared_task(bind=True)
def process_mined_blocks(self):
    for provider in Web3Provider.available.select_related("chain"):
        logger.debug(f"Running task {self.name} by {provider.hostname}")
        try:
            with stream_processor_lock(task=self, provider=provider) as lock:
                if lock.is_acquired:
                    logger.debug(f"Lock acquired for task {self.name} by {provider.hostname}")
                    chain = provider.chain
                    w3: Web3 = make_web3(provider=provider)
                    logger.info(f"Getting blocks from {provider.hostname}")
                    current_block = w3.eth.block_number
                    start = chain.highest_block
                    stop = min(current_block, chain.highest_block + BLOCK_SCAN_RANGE)
                    for block_number in range(start, stop):
                        logger.debug(f"Getting block #{block_number} from {provider.hostname}")
                        block_data = w3.eth.get_block(block_number, full_transactions=True)
                        block_number = block_data.number
                        logger.info(f"Processing block #{block_number} on {provider}")
                        celery_pubsub.publish(
                            "blockchain.mined.block",
                            chain_id=w3.eth.chain_id,
                            block_data=block_data,
                            provider_url=provider.url,
                        )
                        logger.debug(f"Updating chain height to {block_number}")
                        chain.highest_block = block_number
                        lock.refresh()

                    chain.save()
                else:
                    logger.debug(f"Failed to get lock for {provider.hostname}")
        except ExtraDataLengthError as exc:
            if provider.requires_geth_poa_middleware:
                logger.error(f"Failed to get block info from {provider.hostname}: {exc}")
            else:
                logger.warning(f"{provider.hostname} seems to use POA middleware. Updating it.")
                provider.requires_geth_poa_middleware = True
                provider.save()
        except InvalidStatusCode:
            logger.error(f"Could not connect with {provider.hostname} via websocket")


@shared_task(bind=True)
def index_token_transfer_events(self):
    indexer_name = "ethereum_money:token_transfers"

    account_addresses = BaseWallet.objects.values_list("address", flat=True)

    for provider in Web3Provider.available.select_related("chain"):
        event_indexer = EventIndexer.make(provider.chain_id, indexer_name)
        w3: Web3 = make_web3(provider=provider)

        current_block = w3.eth.block_number

        contract = w3.eth.contract(abi=EIP20_ABI)
        abi = contract.events.Transfer._get_event_abi()

        with stream_processor_lock(task=self, provider=provider) as lock:
            while event_indexer.last_block < current_block and lock.is_acquired:
                last_processed = event_indexer.last_block

                from_block = last_processed
                to_block = min(current_block, from_block + provider.max_block_scan_range)

                logger.debug(f"Getting {indexer_name} events between {from_block} and {to_block}")

                _, event_filter_params = construct_event_filter_params(
                    abi, w3.codec, fromBlock=from_block, toBlock=to_block
                )
                try:
                    for log in w3.eth.get_logs(event_filter_params):
                        try:
                            event_data = get_event_data(w3.codec, abi, log)
                            sender = event_data.args._from
                            recipient = event_data.args._to

                            if sender in account_addresses:
                                celery_pubsub.publish(
                                    "blockchain.event.token_transfer.mined",
                                    chain_id=w3.eth.chain_id,
                                    wallet_address=sender,
                                    event_data=event_data,
                                    provider_url=provider.url,
                                )

                            if recipient in account_addresses:
                                celery_pubsub.publish(
                                    "blockchain.event.token_transfer.mined",
                                    chain_id=w3.eth.chain_id,
                                    wallet_address=recipient,
                                    event_data=event_data,
                                    provider_url=provider.url,
                                )

                        except LogTopicError:
                            pass
                        except Exception as exc:
                            logger.exception(f"Unknown error when processing transfer log: {exc}")
                except TimeoutError:
                    logger.error(f"Timeout when getting logs from {provider.hostname}")
                    continue
                except Exception as exc:
                    logger.error(f"Error getting logs from {provider.hostname}: {exc}")
                    continue

                event_indexer.last_block = to_block
                event_indexer.save()

                lock.refresh()


# Tasks that are meant to be run periodically
@shared_task
def reset_inactive_providers():
    Web3Provider.objects.filter(is_active=False).update(synced=False, connected=False)


@shared_task
def refresh_max_priority_fee():
    for provider in Web3Provider.available.filter(supports_eip1559=True):
        try:
            w3 = make_web3(provider=provider)
            MAX_PRIORITY_FEE_TRACKER.set(w3.eth.chain_id, w3.eth.max_priority_fee)
        except Exception as exc:
            logger.info(f"Failed to get max priority fee from {provider.hostname}: {exc}")


@shared_task
def check_providers_configuration():
    for provider in Web3Provider.active.all():
        w3 = make_web3(provider=provider)
        configuration = inspect_web3(w3=w3)
        Web3Provider.objects.filter(id=provider.id).update(**configuration.dict())


@shared_task
def check_providers_are_connected():
    for provider in Web3Provider.active.all():
        logger.info(f"Checking status from {provider.hostname}")
        try:
            w3 = make_web3(provider=provider)
            is_connected = w3.isConnected()
            is_online = is_connected and (
                provider.chain.is_scaling_network or w3.net.peer_count > 0
            )
        except ConnectionError:
            is_online = False
        except ValueError:
            # The node does not support the peer count method. Assume healthy.
            is_online = is_connected
        except Exception as exc:
            logger.error(f"Could not check {provider.hostname}: {exc}")
            continue

        if provider.connected and not is_online:
            logger.info(f"Node {provider.hostname} went offline")
            celery_pubsub.publish(
                "node.connection.nok", chain_id=provider.chain_id, provider_url=provider.url
            )

        elif is_online and not provider.connected:
            logger.info(f"Node {provider.hostname} is back online")
            celery_pubsub.publish(
                "node.connection.ok", chain_id=provider.chain_id, provider_url=provider.url
            )


@shared_task
def check_providers_are_synced():
    for provider in Web3Provider.active.all():
        try:
            w3 = make_web3(provider=provider)
            is_synced = bool(not w3.eth.syncing)
        except (ValueError, AttributeError):
            # The node does not support the eth_syncing method. Assume healthy.
            is_synced = True
        except (ConnectionError, HTTPError) as exc:
            logger.error(f"Failed to connect to {provider.hostname}: {exc}")
            continue

        if provider.synced and not is_synced:
            logger.warn(f"Node {provider.hostname} is out of sync")
            celery_pubsub.publish(
                "node.sync.nok", chain_id=provider.chain_id, provider_url=provider.url
            )
        elif is_synced and not provider.synced:
            logger.info(f"Node {provider.hostname} is back in sync")
            celery_pubsub.publish(
                "node.sync.ok", chain_id=provider.chain_id, provider_url=provider.url
            )


@shared_task
def check_chains_were_reorganized():
    for provider in Web3Provider.active.all():
        with atomic():
            try:
                chain = provider.chain
                w3 = make_web3(provider=provider)
                block_number = w3.eth.block_number
                if chain.highest_block > block_number:
                    chain.blocks.filter(number__gt=block_number).delete()

                chain.highest_block = block_number
                chain.save()
            except InvalidStatusCode:
                logger.error(f"Could not connect with {provider.hostname} via websocket")


@shared_task
def check_payments_in_open_routes():
    CACHE_KEY = "TRANSACTIONS_FOR_OPEN_ROUTES"

    logger.debug("Checking for token transfers in open routes")
    open_routes = BlockchainPaymentRoute.objects.open().select_related(
        "deposit",
        "deposit__currency",
        "deposit__currency__chain",
        "account",
    )

    for route in open_routes:
        logger.info(f"Checking for token transfers for payment {route.deposit_id}")
        token: Token = route.deposit.currency

        # We are only concerned here about ERC20 tokens. Native token
        # transfers are detected directly by the blockchain listeners
        if not token.is_ERC20:
            continue

        provider = Web3Provider.active.filter(chain=token.chain).first()

        if not provider:
            logger.warning(
                f"Route {route} is open but not provider available to check for payments"
            )
            continue

        w3 = make_web3(provider=provider)
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        wallet_address = route.account.address

        event_filter = contract.events.Transfer().createFilter(
            fromBlock=route.start_block_number,
            toBlock=route.expiration_block_number,
            argument_filters={"_to": wallet_address},
        )

        try:
            for transfer_event in event_filter.get_all_entries():
                tx_hash = transfer_event.transactionHash.hex()

                key = f"{CACHE_KEY}:{tx_hash}"

                if cache.get(key):
                    logger.debug(f"Transfer event in tx {tx_hash} has already been published")

                    continue

                logger.debug(f"Publishing transfer event from tx {tx_hash}")
                celery_pubsub.publish(
                    "blockchain.event.token_transfer.mined",
                    chain_id=w3.eth.chain_id,
                    wallet_address=wallet_address,
                    event_data=transfer_event,
                    provider_url=provider.url,
                )
                cache.set(key, True, timeout=BLOCK_CREATION_INTERVAL * 2)
        except ValueError as exc:
            logger.warning(f"Can not get transfer logs from {provider.hostname}: {exc}")


# Tasks that are setup to subscribe and handle events generated by the event streams
@shared_task
def save_historical_data(chain_id, block_data, provider_url):
    logger.debug(f"Adding block #{block_data.number} to historical data from chain #{chain_id}")
    block_history = get_historical_block_data(chain_id)
    block_history.push(block_data)


@shared_task
def notify_new_block(chain_id, block_data, provider_url):
    logger.debug(f"Sending notification of new block on chain #{chain_id}")
    signals.block_sealed.send(sender=Block, chain_id=chain_id, block_data=block_data)


@shared_task
def record_account_transactions(chain_id, block_data, provider_url):

    addresses = BaseWallet.objects.values_list("address", flat=True)

    txs = [
        t for t in block_data["transactions"] if (t["from"] in addresses or t["to"] in addresses)
    ]

    if len(txs) > 0:
        provider = Web3Provider.objects.get(url=provider_url)
        w3 = make_web3(provider=provider)
        assert chain_id == w3.eth.chain_id, f"{provider.hostname} not on chain #{chain_id}"

        for tx_data in txs:
            transaction_receipt = w3.eth.get_transaction_receipt(tx_data.hash)
            tx = Transaction.make(
                chain_id=chain_id,
                tx_receipt=transaction_receipt,
                block_data=block_data,
            )
            for account in BaseWallet.objects.filter(address__in=[tx.from_address, tx.to_address]):
                account.transactions.add(tx)


@shared_task
def record_token_transfers(chain_id, wallet_address, event_data, provider_url):
    token_address = event_data.address
    token = Token.objects.filter(chain_id=chain_id, address=token_address).first()

    if not token:
        return

    sender = event_data.args._from
    recipient = event_data.args._to

    try:
        provider = Web3Provider.objects.get(url=provider_url)
        w3 = make_web3(provider=provider)

        tx_data = w3.eth.get_transaction(event_data.transactionHash)
        tx_receipt = w3.eth.get_transaction_receipt(event_data.transactionHash)
        block_data = w3.eth.get_block(tx_receipt.blockHash)
        amount = token.from_wei(event_data.args._value)

        TransactionDataRecord.make(chain_id=chain_id, tx_data=tx_data)
        tx = Transaction.make(chain_id=chain_id, block_data=block_data, tx_receipt=tx_receipt)

        TransferEvent.objects.create(
            transaction=tx,
            sender=sender,
            recipient=recipient,
            amount=amount.amount,
            currency=amount.currency,
            log_index=event_data.logIndex,
        )

    except TransactionNotFound:
        logger.warning(f"Failed to get transaction {event_data.transactionHash.hex()}")
        return

    tx_hash = event_data.transactionHash.hex()

    account = BaseWallet.objects.filter(address=wallet_address).first()

    if not account:
        logger.warn(f"{wallet_address} is not associated with any known account")
        return

    if account.address == sender:
        logger.debug(
            f"Sending signal of outgoing transfer mined from {account.address} on tx {tx_hash}"
        )
        account.transactions.add(tx)
        signals.outgoing_transfer_mined.send(
            sender=Transaction,
            account=account,
            transaction=tx,
            amount=amount,
            address=recipient,
        )
    elif account.address == recipient:
        logger.debug(
            f"Sending signal of incoming transfer mined from {account.address} on tx {tx_hash}"
        )
        account.transactions.add(tx)
        signals.incoming_transfer_mined.send(
            sender=Transaction,
            account=account,
            transaction=tx,
            amount=amount,
            address=sender,
        )
    else:
        logger.warn(f"Transfer on {tx_hash} generated but is not related to {wallet_address}")


@shared_task
def check_eth_transfers(chain_id, block_data, provider_url):
    addresses = BaseWallet.objects.values_list("address", flat=True)

    txs = [
        t
        for t in block_data["transactions"]
        if t.value > 0 and (t["to"] in addresses or t["from"] in addresses)
    ]

    if not txs:
        return

    chain = Chain.active.get(id=chain_id)
    provider = Web3Provider.objects.get(url=provider_url)
    w3 = make_web3(provider=provider)

    assert chain == provider.chain, f"{provider.hostname} not connected to {chain.name}"

    native_token = Token.make_native(chain=chain)

    for transaction_data in txs:
        sender = transaction_data["from"]
        recipient = transaction_data["to"]

        amount = native_token.from_wei(transaction_data.value)

        transaction_receipt = w3.eth.get_transaction_receipt(transaction_data.hash)
        tx = Transaction.make(
            chain_id=chain_id,
            block_data=block_data,
            tx_receipt=transaction_receipt,
        )

        TransferEvent.objects.create(
            transaction=tx,
            sender=sender,
            recipient=recipient,
            amount=amount.amount,
            currency=amount.currency,
        )
        for account in BaseWallet.objects.filter(address=sender):
            account.transactions.add(tx)
            signals.outgoing_transfer_mined.send(
                sender=Transaction,
                account=account,
                amount=amount,
                transaction=tx,
                address=recipient,
            )

        for account in BaseWallet.objects.filter(address=recipient):
            account.transactions.add(tx)
            signals.incoming_transfer_mined.send(
                sender=Transaction,
                account=account,
                amount=amount,
                transaction=tx,
                address=sender,
            )


@shared_task
def check_pending_transaction_for_eth_transfer(chain_id, transaction_data):
    chain = Chain.actve.get(id=chain_id)

    sender = transaction_data["from"]
    recipient = transaction_data["to"]

    is_native_token_transfer = transaction_data.value != 0

    if not is_native_token_transfer:
        return

    native_token = Token.make_native(chain=chain)
    amount = native_token.from_wei(transaction_data.value)

    for account in BaseWallet.objects.filter(address=sender):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)

        signals.outgoing_transfer_broadcast.send(
            sender=TransactionDataRecord,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )

    for account in BaseWallet.objects.filter(address=recipient):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)

        signals.incoming_transfer_broadcast.send(
            sender=Token,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )


@shared_task
def check_pending_erc20_transfer_event(chain_id, event_data, provider_url):
    try:
        token = Token.objects.get(chain_id=chain_id, address=event_data.address)
    except Token.DoesNotExist:
        return

    sender = event_data.args._from
    recipient = event_data.args._to

    if not BaseWallet.objects.filter(Q(address=sender) | Q(address=recipient)).exists():
        return

    amount = token.from_wei(event_data.args._value)

    try:
        provider = Web3Provider.objects.get(url=provider_url)
        w3 = make_web3(provider=provider)
        transaction_data = w3.eth.get_transaction(event_data.transactionHash)
    except TransactionNotFound:
        logger.warning(f"Failed to get transaction data {event_data.transactionHash.hex()}")
        return

    for account in BaseWallet.objects.filter(address=sender):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)
        signals.outgoing_transfer_broadcast.send(
            sender=TransactionDataRecord,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )

    for account in BaseWallet.objects.filter(address=recipient):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)
        signals.incoming_transfer_broadcast.send(
            sender=TransactionDataRecord,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )


@shared_task
def set_node_connection_ok(chain_id, provider_url):
    logger.info(f"Setting node {provider_url} to online")
    Web3Provider.objects.filter(chain_id=chain_id, url=provider_url).update(connected=True)


@shared_task
def set_node_connection_nok(chain_id, provider_url):
    logger.info(f"Setting node {provider_url} to offline")
    Web3Provider.objects.filter(chain_id=chain_id, url=provider_url).update(connected=False)


@shared_task
def set_node_sync_ok(chain_id, provider_url):
    logger.info(f"Setting node {provider_url} to sync")
    Web3Provider.objects.filter(chain_id=chain_id, url=provider_url).update(synced=True)


@shared_task
def set_node_sync_nok(chain_id, provider_url):
    logger.info(f"Setting node {provider_url} to out-of-sync")
    Web3Provider.objects.filter(chain_id=chain_id, url=provider_url).update(synced=False)


@shared_task
def notify_node_unavailable(chain_id, provider_url):
    broadcast_event(event=Events.PROVIDER_OFFLINE.value, chain_id=chain_id)


@shared_task
def notify_node_recovered(chain_id, provider_url):
    broadcast_event(event=Events.PROVIDER_ONLINE.value, chain_id=chain_id)


def _get_native_token_balance(wallet: Wallet, token: Token, block_data):

    try:
        assert not token.is_ERC20, f"{token} is an ERC20-token"
        provider = Web3Provider.available.get(chain_id=token.chain_id)
    except AssertionError as exc:
        logger.warning(str(exc))
        return
    except Web3Provider.DoesNotExist:
        logger.warning(f"Can not get balance for {wallet}: no provider available")
        return

    w3 = make_web3(provider=provider)

    balance = token.from_wei(
        w3.eth.get_balance(wallet.address, block_identifier=block_data.hash.hex())
    )

    block = Block.make(block_data=block_data, chain_id=token.chain_id)

    WalletBalanceRecord.objects.create(
        wallet=wallet,
        currency=balance.currency,
        amount=balance.amount,
        block=block,
    )


def _get_erc20_token_balance(wallet: Wallet, token: Token, block_data):
    try:
        provider = Web3Provider.available.get(chain_id=token.chain_id)
    except Web3Provider.DoesNotExist:
        logger.warning(f"Can not get balance for {wallet}: no provider available")
        return

    current_record = wallet.current_balance(token)
    current_block = current_record and current_record.block

    w3 = make_web3(provider=provider)

    # Unlike native tokens, we can only get the current balance for
    # ERC20 tokens - i.e, we can not select at block-time. So we need to
    if current_block is None or current_block.number < block_data.number:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        balance = token.from_wei(contract.functions.balanceOf(wallet.address).call())
        block = Block.make(block_data=block_data, chain_id=token.chain_id)

        WalletBalanceRecord.objects.create(
            wallet=wallet,
            currency=balance.currency,
            amount=balance.amount,
            block=block,
        )


@shared_task
def update_all_wallet_balances():
    for provider in Web3Provider.available.all():
        w3 = make_web3(provider=provider)
        chain_id = w3.eth.chain_id
        block_data = w3.eth.get_block(w3.eth.block_number, full_transactions=True)
        for wallet in Wallet.objects.all():
            for token in Token.objects.filter(chain_id=chain_id):
                action = _get_erc20_token_balance if token.is_ERC20 else _get_native_token_balance
                action(wallet=wallet, token=token, block_data=block_data)


@shared_task
def update_wallet_token_balances(chain_id, wallet_address, event_data, provider_url):
    token_address = event_data.address
    token = Token.objects.filter(chain_id=chain_id, address=token_address).first()

    if not token:
        return

    wallet = Wallet.objects.filter(address=wallet_address).first()

    if not wallet:
        return

    provider = Web3Provider.objects.get(url=provider_url)
    w3 = make_web3(provider=provider)

    block_data = w3.eth.get_block(event_data.blockNumber, full_transactions=True)

    _get_erc20_token_balance(wallet=wallet, token=token, block_data=block_data)


@shared_task
def update_wallet_native_token_balances(chain_id, block_data, provider_url):
    addresses = Wallet.objects.values_list("address", flat=True)

    txs = [
        t
        for t in block_data["transactions"]
        if t.value > 0 and (t["to"] in addresses or t["from"] in addresses)
    ]

    if not txs:
        return

    try:
        chain = Chain.active.get(id=chain_id)
    except Chain.DoesNotExist:
        logger.warning(f"Chain {chain_id} not found")
        return

    native_token = Token.make_native(chain=chain)

    for transaction_data in txs:
        sender = transaction_data["from"]
        recipient = transaction_data["to"]

        affected_wallets = Wallet.objects.filter(address__in=[sender, recipient])

        if not affected_wallets.exists():
            return

        for wallet in affected_wallets:
            _get_native_token_balance(wallet=wallet, token=native_token, block_data=block_data)


celery_pubsub.subscribe("blockchain.mined.block", save_historical_data)
celery_pubsub.subscribe("blockchain.mined.block", notify_new_block)
celery_pubsub.subscribe("blockchain.mined.block", record_account_transactions)
celery_pubsub.subscribe("blockchain.mined.block", update_wallet_native_token_balances)
celery_pubsub.subscribe("blockchain.mined.block", check_eth_transfers)
celery_pubsub.subscribe("blockchain.event.token_transfer.mined", update_wallet_token_balances)
celery_pubsub.subscribe("blockchain.event.token_transfer.mined", record_token_transfers)
celery_pubsub.subscribe(
    "blockchain.event.token_transfer.broadcast", check_pending_erc20_transfer_event
)
celery_pubsub.subscribe(
    "blockchain.broadcast.transaction", check_pending_transaction_for_eth_transfer
)
celery_pubsub.subscribe("node.connection.ok", set_node_connection_ok)
celery_pubsub.subscribe("node.connection.nok", set_node_connection_nok)
celery_pubsub.subscribe("node.sync.ok", set_node_sync_ok)
celery_pubsub.subscribe("node.sync.nok", set_node_sync_nok)
celery_pubsub.subscribe("node.sync.nok", notify_node_unavailable)
celery_pubsub.subscribe("node.sync.ok", notify_node_recovered)
celery_pubsub.subscribe("node.connection.nok", notify_node_unavailable)
celery_pubsub.subscribe("node.connection.ok", notify_node_recovered)
