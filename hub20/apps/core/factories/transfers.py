import factory

from hub20.apps.blockchain.factories.providers import EthereumProvider
from hub20.apps.core import models
from hub20.apps.core.choices import WITHDRAWAL_NETWORKS
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


class BlockchainWithdrawalFactory(TransferFactory):
    address = factory.Faker("ethereum_address")
    payment_network = WITHDRAWAL_NETWORKS.blockchain

    class Meta:
        model = models.BlockchainWithdrawal


class RaidenWithdrawalFactory(TransferFactory):
    address = factory.Faker("ethereum_address")
    payment_network = WITHDRAWAL_NETWORKS.raiden
    identifier = factory.fuzzy.FuzzyInteger(2 ** 48, 2 ** 53)

    class Meta:
        model = models.RaidenWithdrawal


__all__ = ["InternalTransferFactory", "BlockchainWithdrawalFactory", "RaidenWithdrawalFactory"]
