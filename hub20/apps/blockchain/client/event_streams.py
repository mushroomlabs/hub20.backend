import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.exceptions import Web3UnsupportedMethod
from hub20.apps.blockchain.models import Chain, Web3Provider

from .web3 import make_web3

logger = logging.getLogger(__name__)
BLOCK_CREATION_INTERVAL = 10  # In seconds
PENDING_TX_POLLING_INTERVAL = 2  # In seconds

PENDING_TX_FILTER_REGISTRY = {}


def _get_pending_tx_filter(w3):
    global PENDING_TX_FILTER_REGISTRY
    try:
        return PENDING_TX_FILTER_REGISTRY[w3.eth.chain_id]
    except KeyError:
        try:
            eth_filter = w3.eth.filter("latest")
        except ValueError:
            raise Web3UnsupportedMethod("filter method not supported")

        PENDING_TX_FILTER_REGISTRY[w3.eth.chain_id] = eth_filter
        return eth_filter


async def generate_web3_providers():
    providers = await sync_to_async(list)(Web3Provider.available.select_related("chain"))

    for provider in providers:
        yield provider


async def generate_blocks(w3: Web3, chain: Chain):
    current_block = w3.eth.block_number
    start = chain.highest_block
    stop = min(current_block, chain.highest_block + BLOCK_SCAN_RANGE)
    for block_number in range(start, stop):
        logger.debug(f"Getting block #{block_number} from {chain}")
        yield w3.eth.get_block(block_number, full_transactions=True)


async def generate_tx_data(w3: Web3, transaction_list):
    for tx_data in transaction_list:
        try:
            tx_receipt = w3.eth.get_transaction_receipt(tx_data.hash)
            yield (tx_data, tx_receipt)
        except TransactionNotFound:
            pass


async def process_mined_blocks():
    while True:
        providers = await sync_to_async(list)(Web3Provider.available.select_related("chain"))
        for provider in providers:
            chain = provider.chain
            w3: Web3 = make_web3(provider=provider)
            logger.info(f"Getting blocks for {chain.name}")
            async for block_data in generate_blocks(w3=w3, chain=provider.chain):
                block_number = block_data.number
                logger.info(f"Processing block #{block_number} on {provider}")
                await sync_to_async(celery_pubsub.publish)(
                    "blockchain.mined.block",
                    chain_id=w3.eth.chain_id,
                    block_data=block_data,
                    provider_url=provider.url,
                )
                chain.highest_block = block_number
                logger.debug(f"Updating chain height to {block_number}")
            await sync_to_async(chain.save)()
        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def process_pending_transactions():
    while True:
        providers = await sync_to_async(list)(
            Web3Provider.available.filter(supports_pending_filters=True).select_related("chain")
        )
        for provider in providers:
            w3: Web3 = make_web3(provider=provider)
            try:
                tx_filter = _get_pending_tx_filter(w3)
                for tx in tx_filter.get_new_entries():
                    tx_hash = tx.hex()
                    logger.info(f"Tx {tx_hash} broadcast by {provider.hostname}")
                    try:
                        tx_data = w3.eth.getTransaction(tx_hash)
                        logger.debug(f"{tx_data['to']} to {tx_data['from']}")
                        await sync_to_async(celery_pubsub.publish)(
                            "blockchain.broadcast.transaction",
                            chain_id=w3.eth.chain_id,
                            transaction_data=tx_data,
                        )
                    except TransactionNotFound:
                        logger.debug(f"Pending tx {tx_hash} not found on {provider.hostname}")
            except (Web3UnsupportedMethod, ValueError):
                logger.warning(
                    f"{provider.hostname} does not support pending filters and will be disabled"
                )
                await sync_to_async(Web3Provider.objects.filter(id=provider).update)(
                    supports_pending_filters=False
                )
            except (HTTPError, ConnectionError):
                logger.warning(f"Failed to connect to {provider.hostname}")
                await sync_to_async(celery_pubsub.publish)(
                    "node.connection.nok",
                    chain_id=provider.chain_id,
                    provider_url=provider.url,
                )
            except Exception:
                logger.exception(f"Failed to get pending txs from {provider.hostname}")

                # We remove the filter in case it was uninstalled by the server, so that we
                # can use a new one
                PENDING_TX_FILTER_REGISTRY.pop(w3.eth.chain_id, None)
        await asyncio.sleep(PENDING_TX_POLLING_INTERVAL)


__all__ = [
    "BLOCK_CREATION_INTERVAL",
    "process_mined_blocks",
    "process_pending_transactions",
]
