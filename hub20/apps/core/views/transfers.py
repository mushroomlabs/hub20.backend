from django.db.models.query import QuerySet
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from .. import models, serializers


class TransferViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.TransferSerializer

    def get_queryset(self) -> QuerySet:
        return models.Transfer.objects.filter(sender=self.request.user).select_subclasses()


__all__ = ["TransferViewSet"]
