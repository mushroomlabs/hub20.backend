import asyncio
import logging

from asgiref.sync import sync_to_async
from web3 import Web3

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.exceptions import Web3UnsupportedMethod
from hub20.apps.blockchain.models import Chain

from .constants import BLOCK_CREATION_INTERVAL
from .utils import get_or_create_eth_filter, log_web3_client_exception, wait_for_connection
from .web3 import get_web3, make_web3

logger = logging.getLogger(__name__)


def web3_filter_event_handler(filter_type, polling_interval):
    def decorator(handler):
        filter_registry = {}

        async def wrapper(*args, **kw):

            while True:
                chains = await sync_to_async(list)(Chain.objects.all())
                for chain in chains:
                    web3_node_host = chain.provider_hostname
                    w3: Web3 = make_web3(provider_url=chain.provider_url)
                    try:
                        eth_filter = get_or_create_eth_filter(filter_registry, w3, filter_type)
                        for event in eth_filter.get_new_entries():
                            try:
                                logger.debug(
                                    f"Running {handler.__name__} for {event.hex()}"
                                    f"on {web3_node_host}"
                                )
                                await handler(w3=w3, chain=chain, event=event)
                            except Exception:
                                logger.exception(
                                    f"Failed to process {str(event)} from {web3_node_host}"
                                )
                    except (Web3UnsupportedMethod, ValueError):
                        logger.warning(f"Failed to install filter at {web3_node_host}")
                    except Exception:
                        logger.exception(
                            f"Failed to get {handler.__name__} events from {web3_node_host}"
                        )

                        # We remove the filter in case it was uninstalled by the server, so that we
                        # can use a new one
                        filter_registry.pop(w3.eth.chain_id, None)
                    await asyncio.sleep(polling_interval)

        return wrapper

    return decorator


def blockchain_scanner(handler):
    async def wrapper(*args, **kw):
        w3: Web3 = get_web3()

        wait_for_connection(w3)
        chain_id = int(w3.net.version)
        chain = await sync_to_async(Chain.make)(chain_id=chain_id)

        starting_block = 0

        while starting_block < chain.highest_block:
            end = min(starting_block + BLOCK_SCAN_RANGE, chain.highest_block)
            try:
                await sync_to_async(handler)(w3=w3, starting_block=starting_block, end_block=end)
            except Exception as exc:
                logger.exception(f"Error on {handler.__name__}: {exc}")

            starting_block += BLOCK_SCAN_RANGE

    return wrapper


def blockchain_mined_block_handler(handler):
    async def wrapper(*args, **kw):
        w3: Web3 = get_web3()
        wait_for_connection(w3=w3)
        block_filter = w3.eth.filter("latest")

        while True:
            try:
                wait_for_connection(w3=w3)
                for block_hash in block_filter.get_new_entries():
                    await sync_to_async(handler)(w3=w3, block_hash=block_hash, *args, **kw)
            except Exception as exc:
                logger.exception(f"Error on {handler.__name__}: {exc}")
            finally:
                await asyncio.sleep(BLOCK_CREATION_INTERVAL)

    return wrapper


def blockchain_pending_transaction_handler(handler):
    async def wrapper(*args, **kw):
        w3: Web3 = get_web3()
        wait_for_connection(w3=w3)
        try:
            tx_filter = w3.eth.filter("pending")
        except ValueError as exc:
            await sync_to_async(log_web3_client_exception)(exc)
            return

        while True:
            try:
                wait_for_connection(w3=w3)
                for tx_hash in tx_filter.get_new_entries():
                    await sync_to_async(handler)(w3=w3, transaction_hash=tx_hash, *args, **kw)
            except Exception as exc:
                logger.exception(f"Error on {handler.__name__}: {exc}")
            finally:
                await asyncio.sleep(BLOCK_CREATION_INTERVAL / 10)

    return wrapper
