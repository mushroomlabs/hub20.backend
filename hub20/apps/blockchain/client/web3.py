import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

from web3 import Web3
from web3.gas_strategies.time_based import fast_gas_price_strategy
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider
from web3.types import TxReceipt

from hub20.apps.blockchain.exceptions import Web3TransactionError
from hub20.apps.blockchain.models import Web3Provider

logger = logging.getLogger(__name__)


def make_web3(provider: Web3Provider) -> Web3:
    endpoint = urlparse(provider.url)

    logger.debug(f"Instantiating new Web3 for {provider.hostname}")
    provider_class = {
        "http": HTTPProvider,
        "https": HTTPProvider,
        "ws": WebsocketProvider,
        "wss": WebsocketProvider,
    }.get(endpoint.scheme, IPCProvider)

    w3 = Web3(provider_class(provider.url))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    w3.eth.setGasPriceStrategy(fast_gas_price_strategy)

    return w3


def send_transaction(
    w3: Web3,
    contract_function,
    account,
    gas,
    contract_args: Optional[Tuple] = None,
    **kw,
) -> TxReceipt:
    nonce = kw.pop("nonce", w3.eth.getTransactionCount(account.address))

    transaction_params = {
        "chainId": int(w3.net.version),
        "nonce": nonce,
        "gasPrice": kw.pop("gas_price", w3.eth.generateGasPrice()),
        "gas": gas,
    }

    transaction_params.update(**kw)

    try:
        result = contract_function(*contract_args) if contract_args else contract_function()
        transaction_data = result.buildTransaction(transaction_params)
        signed = w3.eth.account.signTransaction(transaction_data, account.private_key)
        tx_hash = w3.eth.sendRawTransaction(signed.rawTransaction)
        return w3.eth.waitForTransactionReceipt(tx_hash)
    except ValueError as exc:
        try:
            if exc.args[0].get("message") == "nonce too low":
                logger.warning("Node reported that nonce is too low. Trying tx again...")
                kw["nonce"] = nonce + 1
                return send_transaction(
                    w3,
                    contract_function,
                    account,
                    gas,
                    contract_args=contract_args,
                    **kw,
                )
        except (AttributeError, IndexError):
            pass

        raise Web3TransactionError from exc
