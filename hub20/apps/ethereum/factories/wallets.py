import factory

from hub20.apps.ethereum.factories import BlockFactory

from ..models import (
    BaseWallet,
    HierarchicalDeterministicWallet,
    KeystoreAccount,
    WalletBalanceRecord,
)
from .tokens import Erc20TokenAmountFactory


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


class WalletBalanceRecordFactory(Erc20TokenAmountFactory):
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
