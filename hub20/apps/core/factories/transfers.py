import factory

from hub20.apps.core import models

from .tokens import TokenValueModelFactory
from .users import UserFactory


class TransferFactory(TokenValueModelFactory):
    sender = factory.SubFactory(UserFactory)

    class Meta:
        model = models.Transfer


class InternalTransferFactory(TransferFactory):
    receiver = factory.SubFactory(UserFactory)

    class Meta:
        model = models.InternalTransfer


__all__ = ["TransferFactory", "InternalTransferFactory"]
