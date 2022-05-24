from django.db.models.query import QuerySet
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from .. import models, serializers


class TransferViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.InternalTransferSerializer

    def get_queryset(self) -> QuerySet:
        return models.InternalTransfer.objects.filter(sender=self.request.user)


class WithdrawalViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.WithdrawalSerializer

    def get_queryset(self) -> QuerySet:
        return self.request.user.transfers_sent.filter(
            internaltransfer__isnull=True
        ).select_subclasses()
