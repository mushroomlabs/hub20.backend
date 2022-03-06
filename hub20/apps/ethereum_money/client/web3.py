import logging
from typing import Optional

from django.contrib.auth import get_user_model
from eth_utils import to_checksum_address
from ethereum.abi import ContractTranslator
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.factories.base import FAKER
from hub20.apps.blockchain.models import BaseEthereumAccount, Chain, TransactionDataRecord
from hub20.apps.blockchain.typing import Address, EthereumAccount_T
from hub20.apps.ethereum_money.abi import EIP20_ABI
from hub20.apps.ethereum_money.app_settings import TRANSFER_GAS_LIMIT
from hub20.apps.ethereum_money.models import EthereumToken, EthereumTokenAmount
from hub20.apps.ethereum_money.typing import Web3Client_T

logger = logging.getLogger(__name__)
User = get_user_model()


def encode_transfer_data(recipient_address, amount: EthereumTokenAmount):
    translator = ContractTranslator(EIP20_ABI)
    encoded_data = translator.encode_function_call("transfer", (recipient_address, amount.as_wei))
    return f"0x{encoded_data.hex()}"


def get_transfer_gas_estimate(w3: Web3, token: EthereumToken):
    if token.is_ERC20:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        return contract.functions.transfer(FAKER.ethereum_address(), 0).estimateGas(
            {"from": FAKER.ethereum_address()}
        )
    else:
        return 21000


def get_estimate_fee(w3: Web3, token: EthereumToken) -> EthereumTokenAmount:
    native_token = EthereumToken.make_native(chain=token.chain)

    gas_price = w3.eth.generateGasPrice()
    gas_estimate = get_transfer_gas_estimate(w3=w3, token=token)
    return native_token.from_wei(gas_estimate * gas_price)


def get_max_fee(w3: Web3) -> EthereumTokenAmount:
    chain = Chain.active.get(id=w3.eth.chain_id)
    native_token = EthereumToken.make_native(chain=chain)

    gas_price = chain.gas_price_estimate or w3.eth.generateGasPrice()
    return native_token.from_wei(TRANSFER_GAS_LIMIT * gas_price)


def get_account_balance(w3: Web3, token: EthereumToken, address: Address) -> EthereumTokenAmount:
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


def make_token(w3: Web3, address) -> EthereumToken:
    token_data = get_token_information(w3=w3, address=address)
    chain = Chain.active.get(id=w3.eth.chain_id)
    return EthereumToken.make(chain=chain, address=address, **token_data)


class Web3Client:
    def __init__(self, account: EthereumAccount_T, w3: Optional[Web3] = None) -> None:
        self.account = account

    def build_transfer_transaction(self, recipient, amount: EthereumTokenAmount):
        token = amount.currency

        w3 = make_web3(provider=token.chain.provider)
        chain_id = w3.eth.chain_id
        message = f"Connected to network {chain_id}, token {token.symbol} is on {token.chain_id}"
        assert token.chain_id == chain_id, message

        transaction_params = {
            "chainId": chain_id,
            "nonce": w3.eth.getTransactionCount(self.account.address),
            "gasPrice": w3.eth.generateGasPrice(),
            "gas": TRANSFER_GAS_LIMIT,
            "from": self.account.address,
        }

        if token.is_ERC20:
            transaction_params.update(
                {"to": token.address, "value": 0, "data": encode_transfer_data(recipient, amount)}
            )
        else:
            transaction_params.update({"to": recipient, "value": amount.as_wei})
        return transaction_params

    def transfer(self, amount: EthereumTokenAmount, address, *args, **kw) -> TransactionDataRecord:
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

    def get_balance(self, token: EthereumToken):
        w3 = make_web3(provider=token.chain.provider)
        return get_account_balance(w3=w3, token=token, address=self.account.address)

    @classmethod
    def select_for_transfer(cls, amount: EthereumTokenAmount, address: Address) -> Web3Client_T:

        chain = amount.currency.chain
        w3 = make_web3(provider=chain.provider)

        transfer_fee: EthereumTokenAmount = cls.estimate_transfer_fees(w3=w3)
        assert transfer_fee.is_native_token

        ETH = transfer_fee.currency

        accounts = BaseEthereumAccount.objects.all().order_by("?")

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
    def estimate_transfer_fees(cls, *args, **kw) -> EthereumTokenAmount:
        w3 = kw["w3"]
        return get_max_fee(w3=w3)


__all__ = [
    "encode_transfer_data",
    "get_transfer_gas_estimate",
    "get_estimate_fee",
    "get_max_fee",
    "get_account_balance",
    "get_token_information",
    "make_token",
    "Web3Client",
]
