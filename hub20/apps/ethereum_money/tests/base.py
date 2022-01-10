import logging

from eth_utils import to_wei

from hub20.apps.blockchain.factories import TransactionFactory
from hub20.apps.blockchain.models import Chain, Transaction
from hub20.apps.blockchain.typing import EthereumAccount_T
from hub20.apps.ethereum_money.client import encode_transfer_data
from hub20.apps.ethereum_money.factories import Erc20TransferFactory
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.ethereum_money.signals import incoming_transfer_mined

logger = logging.getLogger(__name__)


def add_eth_to_account(account: EthereumAccount_T, amount: EthereumTokenAmount, chain: Chain):
    tx = TransactionFactory(
        to_address=account.address, value=to_wei(amount.amount, "ether"), block__chain=chain
    )
    account.transactions.add(tx)
    incoming_transfer_mined.send(
        sender=Transaction, transaction=tx, amount=amount, account=account, address=tx.from_address
    )
    return tx


def add_token_to_account(account: EthereumAccount_T, amount: EthereumTokenAmount, chain: Chain):
    logging.debug(f"Creating Transfer transaction of {amount} to {account.address}")
    transaction_data = encode_transfer_data(account.address, amount)
    tx = Erc20TransferFactory(
        to_address=amount.currency.address,
        log__data=transaction_data,
        block__chain=chain,
        value=0,
    )
    account.transactions.add(tx)
    incoming_transfer_mined.send(
        sender=Transaction, transaction=tx, amount=amount, account=account, address=tx.from_address
    )
    return tx
