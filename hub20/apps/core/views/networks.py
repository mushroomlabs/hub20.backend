from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import GenericViewSet

from .. import models, serializers


class PaymentNetworkViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (AllowAny,)
    serializer_class = serializers.PaymentNetworkSerializer

    def get_queryset(self, *args, **kw):
        return models.PaymentNetwork.objects.select_subclasses()


__all__ = ["PaymentNetworkViewSet"]
