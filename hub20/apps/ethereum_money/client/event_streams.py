import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from web3 import Web3
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params
from web3.exceptions import LogTopicError

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.client import BLOCK_CREATION_INTERVAL, make_web3
from hub20.apps.blockchain.client.event_streams import generate_web3_providers
from hub20.apps.blockchain.models import EventIndexer
from hub20.apps.ethereum_money.abi import EIP20_ABI

logger = logging.getLogger(__name__)


def get_transfer_events(w3: Web3, start_block: int, end_block: int):
    contract = w3.eth.contract(abi=EIP20_ABI)
    abi = contract.events.Transfer._get_event_abi()
    _, event_filter_params = construct_event_filter_params(
        abi, w3.codec, fromBlock=start_block, toBlock=end_block
    )
    for log in w3.eth.get_logs(event_filter_params):
        try:
            yield get_event_data(w3.codec, abi, log)
        except LogTopicError:
            pass
        except Exception:
            logger.exception("Unknown error when processing transfer log")


async def process_token_transfer_events():
    indexer_name = "ethereum_money:token_transfers"
    while True:
        async for provider in generate_web3_providers():
            chain = provider.chain
            event_indexer = await sync_to_async(EventIndexer.make)(chain.id, indexer_name)

            w3: Web3 = make_web3(provider=provider)
            current_block = w3.eth.block_number
            last_processed = event_indexer.last_block

            from_block = last_processed
            to_block = min(current_block, from_block + BLOCK_SCAN_RANGE)

            logger.debug(f"Getting {indexer_name} events between {from_block} and {to_block}")
            for event in get_transfer_events(w3=w3, start_block=from_block, end_block=to_block):
                await sync_to_async(celery_pubsub.publish)(
                    "blockchain.event.token_transfer.mined",
                    chain_id=w3.eth.chain_id,
                    event_data=event,
                    provider_url=provider.url,
                )

            event_indexer.last_block = to_block
            await sync_to_async(event_indexer.save)()

            if event_indexer.last_block >= current_block:
                await asyncio.sleep(BLOCK_CREATION_INTERVAL)


__all__ = ["process_token_transfer_events"]
