import factory

from hub20.apps.core.factories import PaymentNetworkFactory

from ..models import BlockchainPaymentNetwork
from .blockchain import SyncedChainFactory


class BlockchainPaymentNetworkFactory(PaymentNetworkFactory):
    name = factory.LazyAttribute(lambda obj: f"Ethereum-compatible blockchain #{obj.chain.id}")
    chain = factory.SubFactory(SyncedChainFactory)

    class Meta:
        model = BlockchainPaymentNetwork
        django_get_or_create = ("chain",)


__all__ = ["BlockchainPaymentNetworkFactory"]
