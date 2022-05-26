import logging

import celery_pubsub
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3
from web3.exceptions import TransactionNotFound

from hub20.apps.ethereum.exceptions import Web3UnsupportedMethod
from hub20.apps.ethereum.models import Web3Provider

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


def process_pending_transactions():
    for provider in Web3Provider.available.filter(supports_pending_filters=True):
        w3: Web3 = make_web3(provider=provider)
        try:
            tx_filter = _get_pending_tx_filter(w3)
            for tx in tx_filter.get_new_entries():
                tx_hash = tx.hex()
                logger.info(f"Tx {tx_hash} broadcast by {provider.hostname}")
                try:
                    tx_data = w3.eth.getTransaction(tx_hash)
                    logger.debug(f"{tx_data['to']} to {tx_data['from']}")
                    celery_pubsub.publish(
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
            Web3Provider.objects.filter(id=provider).update(supports_pending_filters=False)
        except (HTTPError, ConnectionError):
            logger.warning(f"Failed to connect to {provider.hostname}")
            celery_pubsub.publish(
                "node.connection.nok",
                chain_id=provider.chain_id,
                provider_url=provider.url,
            )
        except Exception:
            logger.exception(f"Failed to get pending txs from {provider.hostname}")

            # We remove the filter in case it was uninstalled by the server, so that we
            # can use a new one
            PENDING_TX_FILTER_REGISTRY.pop(w3.eth.chain_id, None)


__all__ = [
    "BLOCK_CREATION_INTERVAL",
    "process_pending_transactions",
]
