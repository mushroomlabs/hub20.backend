import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from django.core.cache import cache
from web3 import Web3

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.client import BLOCK_CREATION_INTERVAL, make_web3
from hub20.apps.blockchain.models import EventIndexer, Web3Provider
from hub20.apps.ethereum_money.abi import EIP20_ABI

logger = logging.getLogger(__name__)


async def process_token_transfer_events():
    indexer_name = "ethereum_money:token_transfers"
    while True:
        providers = await sync_to_async(list)(Web3Provider.available.select_related("chain"))
        for provider in providers:
            chain = provider.chain
            event_indexer = await sync_to_async(EventIndexer.make)(chain.id, indexer_name)

            w3: Web3 = make_web3(provider=provider)
            contract = w3.eth.contract(abi=EIP20_ABI)
            current_block = w3.eth.block_number
            last_processed = event_indexer.last_block

            to_block = min(current_block, last_processed + BLOCK_SCAN_RANGE)
            filter_params = dict(fromBlock=last_processed, toBlock=to_block)

            for transfer_event in contract.events.Transfer().getLogs(filter_params):
                await sync_to_async(celery_pubsub.publish)(
                    "blockchain.event.token_transfer.mined",
                    chain_id=w3.eth.chain_id,
                    event_data=transfer_event,
                    provider_url=provider.url,
                )
            event_indexer.last_block = to_block
            await sync_to_async(event_indexer.save)()
        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def process_pending_token_transfers():
    CACHE_KEY = "PENDING_TOKEN_TRANSFERS"

    while True:
        providers = await sync_to_async(list)(Web3Provider.available.select_related("chain"))
        for provider in providers:
            w3: Web3 = make_web3(provider=provider)
            contract = w3.eth.contract(abi=EIP20_ABI)

            try:
                for transfer_event in contract.events.Transfer().getLogs({"fromBlock": "pending"}):
                    tx_hash = transfer_event.transactionHash.hex()
                    key = f"{CACHE_KEY}:{tx_hash}"

                    if await sync_to_async(cache.get)(key):
                        logger.debug(f"Event for tx {tx_hash} has already been published")
                        continue

                    await sync_to_async(celery_pubsub.publish)(
                        "blockchain.event.token_transfer.broadcast",
                        chain_id=w3.eth.chain_id,
                        event_data=transfer_event,
                        provider_url=provider.url,
                    )
                    await sync_to_async(cache.set)(key, True, timeout=BLOCK_CREATION_INTERVAL * 2)
            except ValueError:
                logger.warning(f"Can not get transfer logs from {provider.hostname}")
        await asyncio.sleep(1)


__all__ = ["process_token_transfer_events", "process_pending_token_transfers"]
