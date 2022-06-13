from django_filters import rest_framework as filters
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.response import Response

from .. import models, serializers
from .base import PolymorphicModelViewSet


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


class PaymentNetworkViewSet(PolymorphicModelViewSet):
    """
    This represents a list of all payment networks known by this hub.
    """

    serializer_class = serializers.PaymentNetworkSerializer
    filterset_class = PaymentNetworkFilter
    filter_backends = (
        SearchFilter,
        filters.DjangoFilterBackend,
    )
    search_fields = ("name",)

    def get_serializer_class(self, **kw):
        if self.action == "status":
            network = self.get_object()
            return serializers.PaymentNetworkStatusSerializer.get_subclassed_serializer(network)

        return super().get_serializer_class()

    def get_queryset(self, *args, **kw):
        active_providers = models.PaymentNetworkProvider.active.all()
        return (
            models.PaymentNetwork.objects.filter(providers__in=active_providers)
            .select_subclasses()
            .distinct()
        )

    @action(detail=True, methods=["GET"], name="Network Status")
    def status(self, request, **kw):
        network = self.get_object().subclassed
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(network, context={"request": request})
        return Response(serializer.data)


__all__ = ["PaymentNetworkViewSet"]
