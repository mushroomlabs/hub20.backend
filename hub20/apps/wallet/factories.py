import factory

from hub20.apps.blockchain.factories import BaseWalletFactory, BlockFactory
from hub20.apps.ethereum_money.factories import EthereumTokenValueModelFactory

from . import models


class KeystoreAccountFactory(BaseWalletFactory):
    class Meta:
        model = models.KeystoreAccount


class HDWalletFactory(BaseWalletFactory):
    index = factory.LazyFunction(lambda: models.HierarchicalDeterministicWallet.objects.count())

    class Meta:
        model = models.HierarchicalDeterministicWallet


class WalletFactory(BaseWalletFactory):
    class Meta:
        model = models.Wallet


class WalletBalanceRecordFactory(EthereumTokenValueModelFactory):
    wallet = factory.SubFactory(WalletFactory)
    block = factory.SubFactory(BlockFactory)

    class Meta:
        model = models.WalletBalanceRecord


EthereumAccountFactory = BaseWalletFactory


__all__ = [
    "EthereumAccountFactory",
    "HDWalletFactory",
    "KeystoreAccountFactory",
    "WalletBalanceRecordFactory",
    "WalletFactory",
]
