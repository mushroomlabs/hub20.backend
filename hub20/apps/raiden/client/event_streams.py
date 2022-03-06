import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from raiden_contracts.constants import CONTRACT_TOKEN_NETWORK
from raiden_contracts.contract_manager import ContractManager, contracts_precompiled_path
from web3 import Web3
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.client import BLOCK_CREATION_INTERVAL, make_web3
from hub20.apps.blockchain.models import EventIndexer, Web3Provider

RAIDEN_CONTRACTS_MANAGER = ContractManager(contracts_precompiled_path())
TOKEN_NETWORK_CONTRACT_ABI = RAIDEN_CONTRACTS_MANAGER.get_contract_abi(CONTRACT_TOKEN_NETWORK)

logger = logging.getLogger(__name__)


def get_token_network_events(w3: Web3, event, start_block: int, end_block: int):
    abi = event._get_event_abi()
    _, event_filter_params = construct_event_filter_params(
        abi, w3.codec, fromBlock=start_block, toBlock=end_block
    )
    for log in w3.eth.get_logs(event_filter_params):
        try:
            yield get_event_data(w3.codec, abi, log)
        except Exception:
            logger.debug("Failed to get event from log")


def get_providers_on_raiden_networks():
    return Web3Provider.available.filter(chain__tokens__tokennetwork__isnull=False).select_related(
        "chain"
    )


async def process_channel_events():
    indexer_name = "raiden:token_network_channels"

    while True:
        providers = await sync_to_async(list)(get_providers_on_raiden_networks())
        for provider in providers:
            event_indexer = await sync_to_async(EventIndexer.make)(provider.chain_id, indexer_name)

            w3 = make_web3(provider=provider)
            contract = w3.eth.contract(abi=TOKEN_NETWORK_CONTRACT_ABI)

            current_block = w3.eth.block_number
            last_processed = event_indexer.last_block
            to_block = min(current_block, last_processed + BLOCK_SCAN_RANGE)

            logger.debug(f"Getting {indexer_name} events between {last_processed} and {to_block}")

            for event_data in get_token_network_events(
                w3, contract.events.ChannelOpened, last_processed, to_block
            ):
                await sync_to_async(celery_pubsub.publish)(
                    "blockchain.event.token_network_channel_opened.mined",
                    chain_id=w3.eth.chain_id,
                    event_data=event_data,
                    provider_url=provider.url,
                )

            for event_data in get_token_network_events(
                w3, contract.events.ChannelClosed, last_processed, to_block
            ):
                await sync_to_async(celery_pubsub.publish)(
                    "blockchain.event.token_network_channel_closed.mined",
                    chain_id=w3.eth.chain_id,
                    event_data=event_data,
                    provider_url=provider.url,
                )

            event_indexer.last_block = to_block
            await sync_to_async(event_indexer.save)()
        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


__all__ = ["process_channel_events"]
