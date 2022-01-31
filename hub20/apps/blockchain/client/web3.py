import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel
from web3 import Web3
from web3.exceptions import ExtraDataLengthError
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider
from web3.types import TxReceipt

from hub20.apps.blockchain import analytics
from hub20.apps.blockchain.exceptions import Web3TransactionError
from hub20.apps.blockchain.models import Web3Provider

logger = logging.getLogger(__name__)


class Web3ProviderConfiguration(BaseModel):
    client_version: Optional[str]
    supports_eip1559: bool
    supports_pending_filters: bool
    requires_geth_poa_middleware: bool


def eip1559_price_strategy(w3: Web3, *args, **kw):
    try:
        current_block = w3.eth.get_block("latest")
        return analytics.recommended_eip1559_gas_price(
            current_block, max_priority_fee=w3.eth.max_priority_fee
        )
    except Exception as exc:
        chain_id = w3.eth.chain_id
        logger.exception(f"Error when getting price estimate for {chain_id}", exc_info=exc)
        return analytics.estimate_gas_price(chain_id)


def historical_trend_price_strategy(w3: Web3, *args, **kw):
    return analytics.estimate_gas_price(w3.eth.chain_id)


def get_web3(provider_url: str) -> Web3:
    endpoint = urlparse(provider_url)

    provider_class = {
        "http": HTTPProvider,
        "https": HTTPProvider,
        "ws": WebsocketProvider,
        "wss": WebsocketProvider,
    }.get(endpoint.scheme, IPCProvider)

    w3 = Web3(provider_class(provider_url))
    return w3


def make_web3(provider: Web3Provider) -> Web3:
    w3 = get_web3(provider_url=provider.url)

    if provider.requires_geth_poa_middleware:
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    price_strategy = (
        eip1559_price_strategy if provider.supports_eip1559 else historical_trend_price_strategy
    )
    w3.eth.setGasPriceStrategy(price_strategy)

    return w3


def inspect_web3(w3: Web3) -> Web3ProviderConfiguration:
    try:
        version: Optional[str] = w3.clientVersion
    except ValueError:
        version = None

    try:
        max_fee = w3.eth.max_priority_fee
        eip1559 = bool(type(max_fee) is int)
    except ValueError:
        eip1559 = False

    try:
        w3.eth.filter("pending")
        pending_filters = True
    except ValueError:
        pending_filters = False

    try:
        w3.eth.get_block("latest")
        requires_geth_poa_middleware = False
    except ExtraDataLengthError:
        requires_geth_poa_middleware = True

    return Web3ProviderConfiguration(
        client_version=version,
        supports_eip1559=eip1559,
        supports_pending_filters=pending_filters,
        requires_geth_poa_middleware=requires_geth_poa_middleware,
    )


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
