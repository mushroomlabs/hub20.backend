import logging
from typing import Optional, Tuple

from eth_utils import to_checksum_address
from ethereum.abi import ContractTranslator
from raiden_contracts.constants import CONTRACT_CUSTOM_TOKEN
from raiden_contracts.contract_manager import ContractManager, contracts_precompiled_path
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.exceptions import TransactionNotFound
from web3.types import TxReceipt

from hub20.apps.core.models import BaseToken, TokenAmount
from hub20.apps.ethereum.abi.tokens import EIP20_ABI
from hub20.apps.ethereum.app_settings import WEB3_TRANSFER_GAS_LIMIT
from hub20.apps.ethereum.exceptions import Web3TransactionError
from hub20.apps.ethereum.factories import FAKER
from hub20.apps.ethereum.models import BaseWallet, Chain, TransactionDataRecord
from hub20.apps.ethereum.typing import Address, EthereumAccount_T, Web3Client_T

logger = logging.getLogger(__name__)

GAS_REQUIRED_FOR_MINT: int = 100_000


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
]
