import factory

from hub20.apps.core.choices import WITHDRAWAL_NETWORKS
from hub20.apps.core.factories.transfers import TransferFactory

from ..models import BlockchainWithdrawal
from .providers import EthereumProvider

factory.Faker.add_provider(EthereumProvider)


class BlockchainWithdrawalFactory(TransferFactory):
    address = factory.Faker("ethereum_address")
    payment_network = WITHDRAWAL_NETWORKS.blockchain

    class Meta:
        model = BlockchainWithdrawal


__all__ = ["BlockchainWithdrawalFactory"]
