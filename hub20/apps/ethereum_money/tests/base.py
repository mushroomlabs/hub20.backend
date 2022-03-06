import logging
from functools import wraps
from unittest.mock import patch

from hub20.apps.blockchain.factories import TransactionFactory
from hub20.apps.blockchain.models import Transaction
from hub20.apps.blockchain.tests.mocks import Web3Mock
from hub20.apps.blockchain.typing import EthereumAccount_T
from hub20.apps.ethereum_money.factories import Erc20TransactionFactory
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.ethereum_money.signals import incoming_transfer_mined

logger = logging.getLogger(__name__)


def use_mock_web3(test_func):
    @wraps(test_func)
    def wrapper(*args, **kw):
        with patch("hub20.apps.ethereum_money.tasks.make_web3") as make_mock_web3:
            make_mock_web3.return_value = Web3Mock
            return test_func(*args, **kw)

    return wrapper


def add_eth_to_account(account: EthereumAccount_T, amount: EthereumTokenAmount):
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


def add_token_to_account(account: EthereumAccount_T, amount: EthereumTokenAmount):
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
