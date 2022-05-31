import factory

from hub20.apps.core.factories import TransferFactory
from hub20.apps.ethereum.factories import EthereumProvider

from ..models import RaidenTransfer
from .networks import RaidenPaymentNetworkFactory

factory.Faker.add_provider(EthereumProvider)


class RaidenTransferFactory(TransferFactory):
    address = factory.Faker("ethereum_address")
    network = factory.SubFactory(RaidenPaymentNetworkFactory)
    identifier = factory.fuzzy.FuzzyInteger(2**48, 2**53)

    class Meta:
        model = RaidenTransfer


__all__ = ["RaidenTransferFactory"]
