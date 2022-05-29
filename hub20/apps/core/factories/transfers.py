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


class TransferConfirmationFactory(factory.django.DjangoModelFactory):
    transfer = factory.SubFactory(TransferFactory)

    class Meta:
        model = models.TransferConfirmation


__all__ = ["TransferFactory", "InternalTransferFactory", "TransferConfirmationFactory"]
