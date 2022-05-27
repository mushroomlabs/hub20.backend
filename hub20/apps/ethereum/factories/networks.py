import factory

from hub20.apps.core.factories import PaymentNetworkFactory

from ..models import BlockchainPaymentNetwork
from .blockchain import SyncedChainFactory


class BlockchainPaymentNetworkFactory(PaymentNetworkFactory):
    name = "Ethereum-compatible blockchain"
    chain = factory.SubFactory(SyncedChainFactory)

    class Meta:
        model = BlockchainPaymentNetwork


__all__ = ["BlockchainPaymentNetworkFactory"]
