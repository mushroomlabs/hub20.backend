import factory

from hub20.apps.core.factories import PaymentNetworkFactory
from hub20.apps.ethereum.factories import SyncedChainFactory

from ..models import RaidenPaymentNetwork


class RaidenPaymentNetworkFactory(PaymentNetworkFactory):
    name = factory.LazyAttribute(lambda obj: f"Raiden connected to #{obj.chain.id}")
    chain = factory.SubFactory(SyncedChainFactory)

    class Meta:
        model = RaidenPaymentNetwork
        django_get_or_create = ("chain",)


__all__ = ["RaidenPaymentNetworkFactory"]
