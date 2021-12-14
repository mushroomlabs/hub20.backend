import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from requests.exceptions import ConnectionError
from web3 import Web3
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain.models import Chain, Web3Provider

from .decorators import web3_filter_event_handler
from .web3 import make_web3

logger = logging.getLogger(__name__)
BLOCK_CREATION_INTERVAL = 10  # In seconds


async def node_online_status():
    while True:
        providers = await sync_to_async(list)(Web3Provider.active.select_related("chain"))
        for provider in providers:
            logger.debug(f"Checking status from {provider.hostname}")
            chain = provider.chain
            try:
                w3 = make_web3(provider=provider)
                is_online = w3.isConnected() and (w3.net.peer_count > 0)
            except ConnectionError:
                is_online = False
            except ValueError:
                # The node does not support the peer count method. Assume healthy.
                is_online = w3.isConnected()

            if is_online:
                await sync_to_async(chain._set_gas_price_estimate)(w3.eth.generate_gas_price())

            if provider.connected and not is_online:
                logger.debug(f"Node {provider.hostname} went offline")
                await sync_to_async(celery_pubsub.publish)(
                    "node.connection.nok", chain_id=chain.id, provider_url=provider.url
                )

            elif is_online and not provider.connected:
                logger.debug(f"Node {provider.hostname} is back online")
                await sync_to_async(celery_pubsub.publish)(
                    "node.connection.ok", chain_id=chain.id, provider_url=provider.url
                )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def node_sync_status():
    while True:
        providers = await sync_to_async(list)(Web3Provider.active.select_related("chain"))
        for provider in providers:
            try:
                w3 = make_web3(provider=provider)
                is_synced = bool(not w3.eth.syncing)
            except ValueError:
                # The node does not support the eth_syncing method. Assume healthy.
                is_synced = True
            except ConnectionError:
                continue

            if provider.synced and not is_synced:
                await sync_to_async(celery_pubsub.publish)(
                    "node.sync.nok", chain_id=provider.chain_id, provider_url=provider.url
                )
            elif is_synced and not provider.synced:
                logger.debug(f"Node {provider.hostname} is back in sync")
                await sync_to_async(celery_pubsub.publish)(
                    "node.sync.ok", chain_id=provider.chain_id, provider_url=provider.url
                )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


@web3_filter_event_handler(filter_type="latest", polling_interval=BLOCK_CREATION_INTERVAL / 2)
async def process_new_block(w3: Web3, chain: Chain, event):
    logger.info(f"New block: {event.hex()}")
    block_data = w3.eth.get_block(event, full_transactions=True)
    await sync_to_async(celery_pubsub.publish)(
        "blockchain.mined.block", chain_id=w3.eth.chain_id, block_data=block_data
    )
    for tx_data in block_data["transactions"]:
        try:
            tx_receipt = w3.eth.get_transaction_receipt(tx_data.hash)
            await sync_to_async(celery_pubsub.publish)(
                "blockchain.mined.transaction",
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
            "blockchain.broadcast.transaction", chain_id=w3.eth.chain_id, transaction_data=tx_data
        )
    except TransactionNotFound:
        logger.info(f"Transaction {tx_hash} not found at pending status")


__all__ = [
    "BLOCK_CREATION_INTERVAL",
    "node_online_status",
    "node_sync_status",
    "process_new_block",
    "process_pending_transaction",
]
