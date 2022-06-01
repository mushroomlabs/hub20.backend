from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from .. import models, serializers


class DepositFilter(filters.FilterSet):
    chain = filters.NumberFilter(field_name="currency__chain")
    token = filters.CharFilter(field_name="currency__address")

    class Meta:
        model = models.Deposit
        fields = ("token", "chain")


class DepositViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.HyperlinkedDepositSerializer
    filterset_class = DepositFilter
    filter_backends = (
        OrderingFilter,
        DjangoFilterBackend,
    )
    ordering = "-created"

    def get_queryset(self) -> QuerySet:
        return self.request.user.deposit_set.all()

    def get_object(self) -> models.Deposit:
        return get_object_or_404(models.Deposit, pk=self.kwargs.get("pk"), user=self.request.user)


class DepositRoutesViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    """
    Manages routes related to a deposit
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.DepositRouteSerializer
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return serializers.PaymentRouteSerializer.get_serializer_class(route=self.get_object())
        return self.serializer_class

    def get_queryset(self, *args, **kw):
        deposit_id = self.kwargs["deposit_pk"]
        return models.PaymentRoute.objects.filter(deposit_id=deposit_id).select_subclasses()

    def get_deposit(self):
        return models.Deposit.objects.get(id=self.kwargs["deposit_pk"])


class PaymentViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self):
        return models.Payment.objects.all()

    def get_permissions(self):
        permission_class = IsAdminUser if self.action == "list" else AllowAny
        return (permission_class(),)

    def get_serializer_class(self):
        if self.action == "list":
            return serializers.PaymentSerializer

        payment = self.get_object()

        return {
            models.InternalPayment: serializers.InternalPaymentSerializer,
            models.BlockchainPayment: serializers.BlockchainPaymentSerializer,
            models.RaidenPayment: serializers.RaidenPaymentSerializer,
        }.get(type(payment), serializers.PaymentSerializer)

    def get_object(self):
        try:
            return models.Payment.objects.get_subclass(id=self.kwargs["pk"])
        except (models.Payment.DoesNotExist, KeyError):
            return None
