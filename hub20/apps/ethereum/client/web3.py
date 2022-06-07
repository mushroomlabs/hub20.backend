import logging
from typing import Optional

from web3 import Web3
from web3.datastructures import AttributeDict
from web3.exceptions import TransactionNotFound

from hub20.apps.core.models import BaseToken, TokenAmount
from hub20.apps.ethereum.abi.tokens import EIP20_ABI
from hub20.apps.ethereum.app_settings import WEB3_TRANSFER_GAS_LIMIT
from hub20.apps.ethereum.models import BaseWallet, EthereumAccount_T, TransactionDataRecord
from hub20.apps.ethereum.typing import Address

logger = logging.getLogger(__name__)

GAS_REQUIRED_FOR_MINT: int = 100_000


def get_account_balance(w3: Web3, token: BaseToken, address: Address) -> TokenAmount:
    if token.is_ERC20:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        return token.from_wei(contract.functions.balanceOf(address).call())
    else:
        return token.from_wei(w3.eth.getBalance(address))


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
    def select_for_transfer(cls, amount: TokenAmount, address: Address):

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


__all__ = ["get_account_balance"]
