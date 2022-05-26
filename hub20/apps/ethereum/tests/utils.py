import logging

from hub20.apps.core.models.tokens import TokenAmount

from ..factories import Erc20TransactionFactory, TransactionFactory
from ..models import Transaction
from ..signals import incoming_transfer_mined
from ..typing import EthereumAccount_T

logger = logging.getLogger(__name__)


def add_eth_to_account(account: EthereumAccount_T, amount: TokenAmount):
    tx = TransactionFactory(to_address=account.address)
    account.transactions.add(tx)
    incoming_transfer_mined.send(
        sender=Transaction,
        transaction=tx,
        amount=amount,
        account=account,
        address=tx.from_address,
    )
    return tx


def add_token_to_account(account: EthereumAccount_T, amount: TokenAmount):
    logging.debug(f"Creating Transfer transaction of {amount} to {account.address}")

    tx = Erc20TransactionFactory(recipient=account.address, amount=amount)
    account.transactions.add(tx)
    incoming_transfer_mined.send(
        sender=Transaction,
        transaction=tx,
        amount=amount,
        account=account,
        address=tx.from_address,
    )
    return tx
