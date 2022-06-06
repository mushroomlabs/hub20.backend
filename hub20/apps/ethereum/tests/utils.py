import logging

from hub20.apps.core.models.tokens import TokenAmount

from ..factories import Erc20TokenTransactionFactory, TransactionFactory, TransferEventFactory
from ..typing import EthereumAccount_T

logger = logging.getLogger(__name__)


def add_eth_to_account(account: EthereumAccount_T, amount: TokenAmount):
    tx = TransactionFactory(to_address=account.address)
    account.transactions.add(tx)
    TransferEventFactory(
        transaction=tx, recipient=account.address, currency=amount.currency, amount=amount.amount
    )
    return tx


def add_token_to_account(account: EthereumAccount_T, amount: TokenAmount):
    logging.debug(f"Creating Transfer transaction of {amount} to {account.address}")

    tx = Erc20TokenTransactionFactory(recipient=account.address, amount=amount)
    account.transactions.add(tx)
    TransferEventFactory(
        transaction=tx, recipient=account.address, currency=amount.currency, amount=amount.amount
    )
    return tx
