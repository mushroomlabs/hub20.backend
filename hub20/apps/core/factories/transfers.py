import factory

from hub20.apps.blockchain.factories.providers import EthereumProvider
from hub20.apps.core import models
from hub20.apps.ethereum_money.factories import EthereumTokenValueModelFactory

from .base import UserFactory

factory.Faker.add_provider(EthereumProvider)


class TransferFactory(EthereumTokenValueModelFactory):
    sender = factory.SubFactory(UserFactory)

    class Meta:
        model = models.Transfer


class InternalTransferFactory(TransferFactory):
    receiver = factory.SubFactory(UserFactory)

    class Meta:
        model = models.InternalTransfer


class BlockchainTransferFactory(TransferFactory):
    address = factory.Faker("ethereum_address")

    class Meta:
        model = models.BlockchainTransfer


class RaidenTransferFactory(TransferFactory):
    address = factory.Faker("ethereum_address")
    identifier = factory.fuzzy.FuzzyInteger(2 ** 48, 2 ** 53)

    class Meta:
        model = models.RaidenTransfer


__all__ = ["InternalTransferFactory", "BlockchainTransferFactory", "RaidenTransferFactory"]
