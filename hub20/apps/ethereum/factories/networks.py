import factory

from hub20.apps.core.factories import PaymentNetworkFactory

from ..models import BlockchainPaymentNetwork, Web3Provider
from .blockchain import SyncedChainFactory


class BlockchainPaymentNetworkFactory(PaymentNetworkFactory):
    name = factory.LazyAttribute(lambda obj: f"Ethereum-compatible blockchain #{obj.chain.id}")
    chain = factory.SubFactory(SyncedChainFactory)

    @factory.post_generation
    def providers(obj, create, extracted, **kw):
        if not create:
            return

        if not extracted:
            Web3ProviderFactory(network=obj)
        else:
            for provider in extracted:
                obj.providers.add(provider)

    class Meta:
        model = BlockchainPaymentNetwork
        django_get_or_create = ("chain",)


class Web3ProviderFactory(factory.django.DjangoModelFactory):
    network = factory.SubFactory(BlockchainPaymentNetworkFactory)
    url = factory.Sequence(lambda n: f"https://web3-{n:02}.example.com")
    connected = True
    is_active = True
    synced = True

    class Meta:
        model = Web3Provider
        django_get_or_create = ("network",)


__all__ = ["BlockchainPaymentNetworkFactory", "Web3ProviderFactory"]
