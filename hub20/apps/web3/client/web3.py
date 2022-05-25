import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

from eth_utils import to_checksum_address
from ethereum.abi import ContractTranslator
from pydantic import BaseModel
from raiden_contracts.constants import CONTRACT_CUSTOM_TOKEN
from raiden_contracts.contract_manager import ContractManager, contracts_precompiled_path
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.exceptions import ExtraDataLengthError, TransactionNotFound
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider
from web3.types import TxReceipt

from hub20.apps.core.abi.tokens import EIP20_ABI
from hub20.apps.core.factories import FAKER
from hub20.apps.core.models import BaseToken, TokenAmount
from hub20.apps.web3 import analytics
from hub20.apps.web3.app_settings import WEB3_REQUEST_TIMEOUT, WEB3_TRANSFER_GAS_LIMIT
from hub20.apps.web3.exceptions import Web3TransactionError
from hub20.apps.web3.models import BaseWallet, Chain, TransactionDataRecord, Web3Provider
from hub20.apps.web3.typing import Address, EthereumAccount_T, Web3Client_T

logger = logging.getLogger(__name__)

GAS_REQUIRED_FOR_MINT: int = 100_000


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

    http_request_params = dict(request_kwargs={"timeout": WEB3_REQUEST_TIMEOUT})
    ws_connection_params = dict(websocket_timeout=WEB3_REQUEST_TIMEOUT)

    params = {
        "http": http_request_params,
        "https": http_request_params,
        "ws": ws_connection_params,
        "wss": ws_connection_params,
    }.get(endpoint.scheme, {})

    w3 = Web3(provider_class(provider_url, **params))
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


def encode_transfer_data(recipient_address, amount: TokenAmount):
    translator = ContractTranslator(EIP20_ABI)
    encoded_data = translator.encode_function_call("transfer", (recipient_address, amount.as_wei))
    return f"0x{encoded_data.hex()}"


def get_transfer_gas_estimate(w3: Web3, token: BaseToken):
    if token.is_ERC20:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        return contract.functions.transfer(FAKER.ethereum_address(), 0).estimateGas(
            {"from": FAKER.ethereum_address()}
        )
    else:
        return 21000


def get_estimate_fee(w3: Web3, token: BaseToken) -> TokenAmount:
    native_token = BaseToken.make_native(chain=token.chain)

    gas_price = w3.eth.generateGasPrice()
    gas_estimate = get_transfer_gas_estimate(w3=w3, token=token)
    return native_token.from_wei(gas_estimate * gas_price)


def get_max_fee(w3: Web3) -> TokenAmount:
    chain = Chain.active.get(id=w3.eth.chain_id)
    native_token = BaseToken.make_native(chain=chain)

    gas_price = chain.gas_price_estimate or w3.eth.generateGasPrice()
    return native_token.from_wei(WEB3_TRANSFER_GAS_LIMIT * gas_price)


def get_account_balance(w3: Web3, token: BaseToken, address: Address) -> TokenAmount:
    if token.is_ERC20:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        return token.from_wei(contract.functions.balanceOf(address).call())
    else:
        return token.from_wei(w3.eth.getBalance(address))


def get_token_information(w3: Web3, address):
    contract = w3.eth.contract(abi=EIP20_ABI, address=to_checksum_address(address))
    return {
        "name": contract.functions.name().call(),
        "symbol": contract.functions.symbol().call(),
        "decimals": contract.functions.decimals().call(),
    }


def make_token(w3: Web3, address) -> BaseToken:
    token_data = get_token_information(w3=w3, address=address)
    chain = Chain.active.get(id=w3.eth.chain_id)
    return BaseToken.make(chain=chain, address=address, **token_data)


def mint_tokens(w3: Web3, account: EthereumAccount_T, amount: TokenAmount):
    logger.debug(f"Minting {amount.formatted}")
    contract_manager = ContractManager(contracts_precompiled_path())
    token_proxy = w3.eth.contract(
        address=to_checksum_address(amount.currency.address),
        abi=contract_manager.get_contract_abi(CONTRACT_CUSTOM_TOKEN),
    )

    send_transaction(
        w3=w3,
        contract_function=token_proxy.functions.mint,
        account=account,
        contract_args=(amount.as_wei,),
        gas=GAS_REQUIRED_FOR_MINT,
    )


class Web3Client:
    def __init__(self, account: EthereumAccount_T, w3: Optional[Web3] = None) -> None:
        self.account = account

    def build_transfer_transaction(self, recipient, amount: TokenAmount):
        token = amount.currency

        w3 = make_web3(provider=token.chain.provider)
        chain_id = w3.eth.chain_id
        message = f"Connected to network {chain_id}, token {token.symbol} is on {token.chain_id}"
        assert token.chain_id == chain_id, message

        transaction_params = {
            "chainId": chain_id,
            "nonce": w3.eth.getTransactionCount(self.account.address),
            "gasPrice": w3.eth.generateGasPrice(),
            "gas": WEB3_TRANSFER_GAS_LIMIT,
            "from": self.account.address,
        }

        if token.is_ERC20:
            transaction_params.update(
                {"to": token.address, "value": 0, "data": encode_transfer_data(recipient, amount)}
            )
        else:
            transaction_params.update({"to": recipient, "value": amount.as_wei})
        return transaction_params

    def transfer(self, amount: TokenAmount, address, *args, **kw) -> TransactionDataRecord:
        w3 = make_web3(provider=amount.currency.chain.provider)
        transfer_transaction_data = self.build_transfer_transaction(
            recipient=address, amount=amount
        )
        signed_tx = self.sign_transaction(transaction_data=transfer_transaction_data, w3=w3)
        chain_id = w3.eth.chain_id
        tx_hash = w3.eth.sendRawTransaction(signed_tx.rawTransaction)
        try:
            tx_data = w3.eth.get_transaction(tx_hash)
            return TransactionDataRecord.make(chain_id=chain_id, tx_data=tx_data, force=True)
        except TransactionNotFound:
            return TransactionDataRecord.make(
                chain_id=chain_id, tx_data=AttributeDict(transfer_transaction_data)
            )

    def sign_transaction(self, transaction_data, w3: Web3, *args, **kw):
        if not hasattr(self.account, "private_key"):
            raise NotImplementedError("Can not sign transaction without the private key")
        return w3.eth.account.signTransaction(transaction_data, self.account.private_key)

    def get_balance(self, token: BaseToken):
        w3 = make_web3(provider=token.chain.provider)
        return get_account_balance(w3=w3, token=token, address=self.account.address)

    @classmethod
    def select_for_transfer(cls, amount: TokenAmount, address: Address) -> Web3Client_T:

        chain = amount.currency.chain
        w3 = make_web3(provider=chain.provider)

        transfer_fee: TokenAmount = cls.estimate_transfer_fees(w3=w3)
        assert transfer_fee.is_native_token

        ETH = transfer_fee.currency

        accounts = BaseWallet.objects.all().order_by("?")

        if amount.is_native_token:
            amount += transfer_fee

        for account in accounts:
            get_balance = lambda t: get_account_balance(w3=w3, token=t, address=account.address)

            eth_balance = get_balance(ETH)
            token_balance = eth_balance if amount.is_native_token else get_balance(amount.currency)

            if eth_balance >= transfer_fee and token_balance >= amount:
                return cls(account=account, w3=w3)
        else:
            raise ValueError("No account with enough funds for this transfer")

    @classmethod
    def estimate_transfer_fees(cls, *args, **kw) -> TokenAmount:
        w3 = kw["w3"]
        return get_max_fee(w3=w3)


__all__ = [
    "encode_transfer_data",
    "get_transfer_gas_estimate",
    "get_estimate_fee",
    "get_max_fee",
    "get_account_balance",
    "get_token_information",
    "inspect_web3",
    "make_token",
    "make_web3",
]
