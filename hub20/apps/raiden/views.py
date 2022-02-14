from django.db.models.query import QuerySet
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from . import models, serializers


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


class ServiceDepositMixin(BaseRaidenViewMixin):
    serializer_class = serializers.ServiceDepositSerializer
    queryset = models.UserDepositContractOrder.objects.all()


class ServiceDepositListView(ServiceDepositMixin, generics.ListCreateAPIView):
    pass


class ServiceDepositDetailView(ServiceDepositMixin, generics.RetrieveAPIView):
    pass


class TokenNetworkViewMixin:
    permission_classes = (IsAdminUser,)
    serializer_class = serializers.TokenNetworkSerializer
    lookup_field = "address"
    lookup_url_kwarg = "address"
    queryset: QuerySet = models.TokenNetwork.objects.all()


class TokenNetworkViewSet(
    TokenNetworkViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    def destroy(self, request, *args, **kw):
        raiden = models.Raiden.objects.first()

        if raiden:
            models.LeaveTokenNetworkOrder.objects.create(
                raiden=raiden, user=request.user, token_network=self.get_object()
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True, methods=["post"], serializer_class=serializers.JoinTokenNetworkOrderSerializer
    )
    def join(self, request, address=None):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
