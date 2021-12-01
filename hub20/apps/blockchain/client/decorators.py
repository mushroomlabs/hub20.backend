import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3

from hub20.apps.blockchain.exceptions import Web3UnsupportedMethod
from hub20.apps.blockchain.models import Chain

from .web3 import make_web3

logger = logging.getLogger(__name__)


def _get_or_create_eth_filter(registry, w3, filter_type):
    try:
        return registry[w3.eth.chain_id]
    except KeyError:
        try:
            eth_filter = w3.eth.filter(filter_type)
        except ValueError:
            raise Web3UnsupportedMethod("filter method not supported")
        registry[w3.eth.chain_id] = eth_filter
        return eth_filter


def web3_filter_event_handler(filter_type, polling_interval):
    def decorator(handler):
        filter_registry = {}

        async def wrapper(*args, **kw):

            while True:
                chains = await sync_to_async(list)(Chain.available.all())
                for chain in chains:
                    web3_node_host = chain.provider_hostname
                    w3: Web3 = make_web3(provider_url=chain.provider_url)
                    try:
                        eth_filter = _get_or_create_eth_filter(filter_registry, w3, filter_type)
                        for event in eth_filter.get_new_entries():
                            try:
                                logger.debug(
                                    f"Running {handler.__name__} for {event.hex()}"
                                    f"on {web3_node_host}"
                                )
                                await handler(w3=w3, chain=chain, event=event)
                            except Exception:
                                logger.exception(
                                    f"Failed to process {str(event.hex())} from {web3_node_host}"
                                )
                    except (Web3UnsupportedMethod, ValueError):
                        logger.warning(f"Failed to install filter at {web3_node_host}")
                    except (HTTPError, ConnectionError):
                        await sync_to_async(celery_pubsub.publish)(
                            "node.connection.nok",
                            chain_id=chain.id,
                            provider_url=chain.provider_url,
                        )
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
