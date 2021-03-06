import factory

from hub20.apps.core.factories import TransferConfirmationFactory, TransferFactory

from ..models import BlockchainTransfer, BlockchainTransferConfirmation
from .blockchain import TransactionFactory
from .networks import BlockchainPaymentNetworkFactory


class BlockchainTransferFactory(TransferFactory):
    address = factory.Faker("ethereum_address")
    network = factory.SubFactory(BlockchainPaymentNetworkFactory)

    class Meta:
        model = BlockchainTransfer


class BlockchainTransferConfirmationFactory(TransferConfirmationFactory):
    transfer = factory.SubFactory(BlockchainTransferFactory)
    transaction = factory.SubFactory(TransactionFactory)

    class Meta:
        model = BlockchainTransferConfirmation


__all__ = ["BlockchainTransferFactory", "BlockchainTransferConfirmationFactory"]
