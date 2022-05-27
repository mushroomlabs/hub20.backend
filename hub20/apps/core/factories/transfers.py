import factory

from hub20.apps.core import models

from .networks import InternalPaymentNetworkFactory
from .tokens import TokenValueModelFactory
from .users import UserFactory


class TransferFactory(TokenValueModelFactory):
    sender = factory.SubFactory(UserFactory)

    class Meta:
        model = models.Transfer


class InternalTransferFactory(TransferFactory):
    receiver = factory.SubFactory(UserFactory)
    network = factory.SubFactory(InternalPaymentNetworkFactory)

    class Meta:
        model = models.InternalTransfer


__all__ = ["TransferFactory", "InternalTransferFactory"]
