import decimal
import os
import random

import factory
from eth_account.account import Account
from faker import Faker
from faker.providers import BaseProvider
from hexbytes import HexBytes

from .blockchain import *  # noqa
from .checkout import *  # noqa
from .networks import *  # noqa
from .payments import *  # noqa
from .tokens import *  # noqa
from .transfers import *  # noqa
from .wallets import *  # noqa


class EthereumProvider(BaseProvider):
    def ethereum_address(self):
        private_key = os.urandom(32)
        account = Account.from_key(private_key)
        return account.address

    def hex64(self):
        return HexBytes(os.urandom(32))

    def uint256(self):
        return decimal.Decimal(random.randint(1, 2**256))


FAKER = Faker()
FAKER.add_provider(EthereumProvider)
factory.Faker.add_provider(EthereumProvider)
