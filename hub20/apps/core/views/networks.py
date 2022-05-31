from django_filters import rest_framework as filters
from rest_framework.filters import SearchFilter
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import GenericViewSet

from .. import models, serializers


class PaymentNetworkFilter(filters.FilterSet):
    available = filters.BooleanFilter(label="available", method="filter_available")
    connected = filters.BooleanFilter(label="connected", method="filter_connected")

    def filter_available(self, queryset, name, value):
        action = queryset.filter if value else queryset.exclude
        return action(providers__in=models.PaymentNetworkProvider.available.all())

    def filter_connected(self, queryset, name, value):
        action = queryset.filter if value else queryset.exclude
        return action(providers__in=models.PaymentNetworkProvider.connected.all())

    class Meta:
        model = models.PaymentNetwork
        fields = ("available", "connected")


class PaymentNetworkViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    """
    This represents a list of all payment networks known by this hub.
    """

    permission_classes = (AllowAny,)
    serializer_class = serializers.PaymentNetworkSerializer
    filterset_class = PaymentNetworkFilter
    filter_backends = (
        SearchFilter,
        filters.DjangoFilterBackend,
    )
    search_fields = ("name",)

    def get_queryset(self, *args, **kw):
        return models.PaymentNetwork.objects.filter(
            providers__in=models.PaymentNetworkProvider.active.all()
        ).select_subclasses()


__all__ = ["PaymentNetworkViewSet"]
