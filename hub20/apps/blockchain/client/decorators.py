import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3

from hub20.apps.blockchain.exceptions import Web3UnsupportedMethod
from hub20.apps.blockchain.models import Web3Provider

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
                providers = await sync_to_async(list)(
                    Web3Provider.available.select_related("chain")
                )
                for provider in providers:
                    chain = provider.chain
                    w3: Web3 = make_web3(provider=provider)
                    try:
                        eth_filter = _get_or_create_eth_filter(filter_registry, w3, filter_type)
                        for event in eth_filter.get_new_entries():
                            try:
                                logger.debug(
                                    f"Running {handler.__name__} for {event.hex()}"
                                    f"on {provider.hostname}"
                                )
                                await handler(w3=w3, chain=chain, event=event)
                            except Exception:
                                logger.exception(
                                    f"Failed to process {event.hex()} from {provider.hostname}"
                                )
                    except (Web3UnsupportedMethod, ValueError):
                        logger.warning(f"Failed to install filter at {provider.hostname}")
                    except (HTTPError, ConnectionError):
                        await sync_to_async(celery_pubsub.publish)(
                            "node.connection.nok",
                            chain_id=chain.id,
                            provider_url=provider.url,
                        )
                    except Exception:
                        logger.exception(
                            f"Failed to get {handler.__name__} events from {provider.hostname}"
                        )

                        # We remove the filter in case it was uninstalled by the server, so that we
                        # can use a new one
                        filter_registry.pop(w3.eth.chain_id, None)
                    await asyncio.sleep(polling_interval)

        return wrapper

    return decorator
