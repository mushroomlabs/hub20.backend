import logging

from hub20.apps.core.factories import Erc20TransactionFactory, TransactionFactory
from hub20.apps.core.models import TokenAmount, Transaction
from hub20.apps.core.signals import incoming_transfer_mined
from hub20.apps.core.typing import EthereumAccount_T

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
