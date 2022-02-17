from django.db.models.query import QuerySet
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import GenericViewSet

from . import models, serializers


class WalletViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAdminUser,)
    serializer_class = serializers.WalletSerializer
    lookup_url_kwarg = "address"
    lookup_field = "address"

    def get_queryset(self) -> QuerySet:
        return models.Wallet.objects.all()
