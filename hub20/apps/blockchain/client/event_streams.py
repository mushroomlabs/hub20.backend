import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from web3 import Web3
from web3.exceptions import TransactionNotFound
from requests.exceptions import ConnectionError

from hub20.apps.blockchain.models import Chain

from .constants import BLOCK_CREATION_INTERVAL
from .decorators import web3_filter_event_handler
from .utils import is_connected_to_blockchain
from .web3 import make_web3

logger = logging.getLogger(__name__)


async def node_online_status():
    while True:
        chains = await sync_to_async(list)(Chain.objects.filter(enabled=True))
        for chain in chains:
            try:
                w3 = make_web3(provider_url=chain.provider_url)
                is_online = is_connected_to_blockchain(w3=w3)
            except ConnectionError:
                is_online = False
            except ValueError:
                # The node does not support the peer count method. Assume healthy.
                is_online = w3.isConnected()

            if chain.online and not is_online:
                logger.debug(f"Node {chain.provider_hostname} went offline")
                await sync_to_async(celery_pubsub.publish)(
                    "node.connection.nok", chain_id=chain.id, provider_url=chain.provider_url
                )

            elif is_online and not chain.online:
                logger.debug(f"Node {chain.provider_hostname} is back online")
                await sync_to_async(celery_pubsub.publish)(
                    "node.connection.ok", chain_id=chain.id, provider_url=chain.provider_url
                )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def node_sync_status():
    while True:
        chains = await sync_to_async(list)(Chain.objects.filter(enabled=True))
        for chain in chains:
            try:
                w3 = make_web3(provider_url=chain.provider_url)
                is_synced = bool(not w3.eth.syncing)
            except ValueError:
                # The node does not support the eth_syncing method. Assume healthy.
                is_synced = True
            except ConnectionError:
                continue

            if chain.synced and not is_synced:
                await sync_to_async(celery_pubsub.publish)(
                    "node.sync.nok", provider_url=chain.provider_url
                )
            elif is_synced and not chain.synced:
                logger.debug(f"Node {chain.provider_hostname} is back in sync")
                await sync_to_async(celery_pubsub.publish)(
                    "node.sync.ok", provider_url=chain.provider_url
                )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


@web3_filter_event_handler(filter_type="latest", polling_interval=BLOCK_CREATION_INTERVAL / 2)
async def process_new_block(w3: Web3, chain: Chain, event):
    logger.info(f"New block: {event.hex()}")
    block_data = w3.eth.get_block(event, full_transactions=True)
    await sync_to_async(celery_pubsub.publish)(
        "blockchain.block.mined", chain_id=w3.eth.chain_id, block_data=block_data
    )
    for tx_data in block_data["transactions"]:
        try:
            tx_receipt = w3.eth.get_transaction_receipt(tx_data.hash)
            await sync_to_async(celery_pubsub.publish)(
                "blockchain.transaction.mined",
                chain_id=w3.eth.chain_id,
                block_data=block_data,
                transaction_data=tx_data,
                transaction_receipt=tx_receipt,
            )
        except TransactionNotFound:
            pass


@web3_filter_event_handler(filter_type="pending", polling_interval=2)
async def process_pending_transaction(w3: Web3, chain: Chain, event):
    tx_hash = event.hex()
    logger.info(f"Pending tx broadcast: {tx_hash}")
    try:
        tx_data = w3.eth.getTransaction(tx_hash)
        logger.debug(f"{tx_data['to']} to {tx_data['from']}")
        await sync_to_async(celery_pubsub.publish)(
            "blockchain.transaction.broadcast", chain_id=w3.eth.chain_id, transaction_data=tx_data
        )
    except TransactionNotFound:
        logger.info(f"Transaction {tx_hash} not found at pending status")
