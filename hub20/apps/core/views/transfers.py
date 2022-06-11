from django.db.models.query import QuerySet
from rest_framework.mixins import CreateModelMixin

from .. import models, serializers
from .base import PolymorphicModelViewSet, UserDataViewSet


class TransferViewSet(UserDataViewSet, CreateModelMixin):
    serializer_class = serializers.InternalTransferSerializer

    def get_queryset(self) -> QuerySet:
        return models.InternalTransfer.objects.filter(sender=self.request.user)


class WithdrawalViewSet(PolymorphicModelViewSet, UserDataViewSet):
    serializer_class = serializers.BaseWithdrawalSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            transfer = self.get_object()
            return self.serializer_class.get_subclassed_serializer(transfer.network.subclassed)

        return self.serializer_class

    def get_queryset(self) -> QuerySet:
        return self.request.user.transfers_sent.exclude(
            internaltransfer__isnull=False
        ).select_subclasses()


class NetworkWithdrawalViewSet(PolymorphicModelViewSet, UserDataViewSet, CreateModelMixin):
    """
    Sets up a new withdraw action on this payment network
    """

    serializer_class = serializers.BaseWithdrawalSerializer

    def get_network(self):
        return models.PaymentNetwork.objects.get_subclass(id=self.kwargs["network_pk"])

    def get_serializer_class(self):
        network = self.get_network()
        return self.serializer_class.get_subclassed_serializer(network)

    def get_queryset(self) -> QuerySet:
        return self.request.user.transfers_sent.filter(
            network=self.get_network()
        ).select_subclasses()


__all__ = ["TransferViewSet", "WithdrawalViewSet", "NetworkWithdrawalViewSet"]
