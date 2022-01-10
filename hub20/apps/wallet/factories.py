import factory

from hub20.apps.blockchain.factories import BaseWalletFactory

from .models import HierarchicalDeterministicWallet, KeystoreAccount


class KeystoreAccountFactory(BaseWalletFactory):
    class Meta:
        model = KeystoreAccount


class HDWalletFactory(BaseWalletFactory):
    index = factory.LazyFunction(lambda: HierarchicalDeterministicWallet.objects.count())

    class Meta:
        model = HierarchicalDeterministicWallet


EthereumAccountFactory = BaseWalletFactory

__all__ = ["EthereumAccountFactory", "HDWalletFactory", "KeystoreAccount"]
