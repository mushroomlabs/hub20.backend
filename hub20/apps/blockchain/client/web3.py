import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

from django.db.models import Avg
from web3 import Web3
from web3.gas_strategies.time_based import fast_gas_price_strategy
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider
from web3.types import TxParams, TxReceipt, Wei

from hub20.apps.blockchain.exceptions import Web3TransactionError
from hub20.apps.blockchain.models import Transaction

logger = logging.getLogger(__name__)


def database_history_gas_price_strategy(w3: Web3, params: Optional[TxParams] = None) -> Wei:

    BLOCK_HISTORY_SIZE = 100
    chain_id = int(w3.net.version)
    current_block_number = w3.eth.blockNumber

    txs = Transaction.objects.filter(
        block__chain=chain_id,
        block__number__gte=current_block_number - BLOCK_HISTORY_SIZE,
    )
    avg_price = txs.aggregate(avg_price=Avg("gas_price")).get("avg_price")
    if avg_price:
        wei_price = int(avg_price)
        logger.debug(f"Average Gas Price in last {txs.count()} transactions: {wei_price} wei")
        return Wei(wei_price)
    else:
        logger.debug("No transactions to determine gas price. Default to 'fast' strategy")
        return fast_gas_price_strategy(web3=w3, transaction_params=params)


def make_web3(provider_url: str) -> Web3:
    endpoint = urlparse(provider_url)
    logger.debug(f"Instantiating new Web3 for {endpoint.hostname}")
    provider_class = {
        "http": HTTPProvider,
        "https": HTTPProvider,
        "ws": WebsocketProvider,
        "wss": WebsocketProvider,
    }.get(endpoint.scheme, IPCProvider)

    w3 = Web3(provider_class(provider_url))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    w3.eth.setGasPriceStrategy(database_history_gas_price_strategy)

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
