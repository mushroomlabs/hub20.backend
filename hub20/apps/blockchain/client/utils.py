import logging
import time

from web3 import Web3

from hub20.apps.blockchain.exceptions import Web3UnsupportedMethod

from .constants import BLOCK_CREATION_INTERVAL

logger = logging.getLogger(__name__)


def is_connected_to_blockchain(w3: Web3):
    return w3.isConnected() and (w3.net.peer_count > 0)


def wait_for_connection(w3: Web3):
    while not is_connected_to_blockchain(w3=w3):
        logger.info("Not connected to blockchain. Waiting for reconnection...")
        time.sleep(BLOCK_CREATION_INTERVAL / 2)


def log_web3_client_exception(web3_exception):
    """
    Some of the web3 client errors (e.g, rpc methods not supported
    by Infura) comes as a `ValueError` exception with both a `code`
    and a `message` attribute. This is just a convenience function to
    warn the user about the error
    """
    try:
        error_response = web3_exception.args[0]
        error_message = error_response["message"]
        logger.warning(f"Can not get pending transaction filter: {error_message}")
    except (IndexError, KeyError):
        # Nope. This is not the expected error
        logger.exception(web3_exception)


def get_or_create_eth_filter(registry, w3, filter_type):
    try:
        return registry[w3.eth.chain_id]
    except KeyError:
        try:
            eth_filter = w3.eth.filter(filter_type)
        except ValueError:
            raise Web3UnsupportedMethod("filter method not supported")
        registry[w3.eth.chain_id] = eth_filter
        return eth_filter
