import factory

from hub20.apps.ethereum_money.factories import TokenValueModelFactory
from hub20.apps.web3.factories import BlockFactory

from ..models import (
    BaseWallet,
    HierarchicalDeterministicWallet,
    KeystoreAccount,
    WalletBalanceRecord,
)


class BaseWalletFactory(factory.django.DjangoModelFactory):
    address = factory.Faker("ethereum_address")

    class Meta:
        model = BaseWallet
        django_get_or_create = ("address",)


class KeystoreAccountFactory(BaseWalletFactory):
    class Meta:
        model = KeystoreAccount


class HDWalletFactory(BaseWalletFactory):
    index = factory.LazyFunction(lambda: HierarchicalDeterministicWallet.objects.count())

    class Meta:
        model = HierarchicalDeterministicWallet


class WalletBalanceRecordFactory(TokenValueModelFactory):
    wallet = factory.SubFactory(BaseWalletFactory)
    block = factory.SubFactory(BlockFactory)

    class Meta:
        model = WalletBalanceRecord


EthereumAccountFactory = BaseWalletFactory


__all__ = [
    "BaseWalletFactory",
    "EthereumAccountFactory",
    "HDWalletFactory",
    "KeystoreAccountFactory",
    "WalletBalanceRecordFactory",
]
