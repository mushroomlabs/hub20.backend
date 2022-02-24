from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.mixins import (
    CreateModelMixin,
    DestroyModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from hub20.apps.blockchain.models import Chain

from . import models, serializers


class TokenNetworkFilter(filters.FilterSet):
    chain_id = filters.ModelChoiceFilter(
        label="chain", method="filter_by_chain", queryset=Chain.active.all()
    )
    connected = filters.BooleanFilter(label="connected", method="filter_connected")

    def filter_connected(self, queryset, name, value):
        return queryset.exclude(channel__isnull=value)

    def filter_by_chain(self, queryset, name, value):
        return queryset.filter(token__chain_id=value)

    class Meta:
        model = models.TokenNetwork
        ordering_fields = ("chain_id", "token__name")
        fields = ("chain_id", "connected")


class BaseRaidenViewMixin:
    permission_classes = (IsAdminUser,)


class RaidenViewSet(
    BaseRaidenViewMixin,
    GenericViewSet,
    ListModelMixin,
    RetrieveModelMixin,
):
    serializer_class = serializers.RaidenSerializer
    queryset = models.Raiden.objects.all()

    @action(detail=True, methods=["get"], serializer_class=serializers.RaidenStatusSerializer)
    def status(self, request, pk=None):
        serializer = self.get_serializer(instance=self.get_object())
        return Response(serializer.data)


class ChannelViewSet(BaseRaidenViewMixin, GenericViewSet, ListModelMixin, RetrieveModelMixin):
    serializer_class = serializers.ChannelSerializer

    def get_queryset(self, *args, **kw):
        return models.Channel.objects.filter(raiden_id=self.kwargs["raiden_pk"])


class ChannelDepositViewSet(
    BaseRaidenViewMixin, GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin
):
    serializer_class = serializers.ChannelDepositSerializer

    def get_queryset(self, *args, **kw):
        return models.ChannelDepositOrder.objects.filter(channel_id=self.kwargs["channel_pk"])

    def get_object(self, *args, **kw):
        return models.ChannelDepositOrder.objects.filter(pk=self.kwargs["pk"]).first()


class ChannelWithdrawalViewSet(
    BaseRaidenViewMixin, GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin
):
    serializer_class = serializers.ChannelWithdrawalSerializer
    queryset = models.ChannelWithdrawOrder.objects.all()


class ServiceDepositViewSet(
    BaseRaidenViewMixin, GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin
):
    serializer_class = serializers.ServiceDepositSerializer

    def get_queryset(self, *args, **kw):
        return models.UserDepositContractOrder.objects.filter(raiden_id=self.kwargs["raiden_pk"])


class TokenNetworkViewMixin(viewsets.GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAdminUser,)
    serializer_class = serializers.TokenNetworkSerializer

    def get_queryset(self) -> QuerySet:
        return models.TokenNetwork.objects.all()


class TokenNetworkViewSet(TokenNetworkViewMixin):
    lookup_field = "address"
    lookup_url_kwarg = "address"
    filterset_class = TokenNetworkFilter
    filter_backends = (filters.DjangoFilterBackend,)


class RaidenTokenNetworkViewSet(
    viewsets.GenericViewSet,
    ListModelMixin,
    RetrieveModelMixin,
    DestroyModelMixin,
    CreateModelMixin,
):
    serializer_class = serializers.JoinTokenNetworkOrderSerializer

    def get_raiden(self):
        return get_object_or_404(models.Raiden, id=self.kwargs["raiden_pk"])

    def get_queryset(self) -> QuerySet:
        raiden = self.get_raiden()
        return models.JoinTokenNetworkOrder.objects.filter(raiden=raiden)

    def destroy(self, request, *args, **kw):
        raiden = self.get_raiden()

        models.LeaveTokenNetworkOrder.objects.create(
            raiden=raiden, user=request.user, token_network=self.get_object()
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
