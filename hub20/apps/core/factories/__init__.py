import decimal
import os
import random

import ethereum
from faker import Faker
from faker.providers import BaseProvider
from hexbytes import HexBytes

from .accounting import *  # noqa
from .networks import *  # noqa
from .payments import *  # noqa
from .store import *  # noqa
from .tokens import *  # noqa
from .transfers import *  # noqa
from .users import *  # noqa


class EthereumProvider(BaseProvider):
    def ethereum_address(self):
        private_key = os.urandom(32)
        address = ethereum.utils.privtoaddr(private_key)
        return ethereum.utils.checksum_encode(address)

    def hex64(self):
        return HexBytes(os.urandom(32))

    def uint256(self):
        return decimal.Decimal(random.randint(1, 2**256))


FAKER = Faker()
FAKER.add_provider(EthereumProvider)
