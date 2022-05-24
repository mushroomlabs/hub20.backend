from django.db.models.query import QuerySet
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .models import BaseWallet, Chain
from .serializers import ChainSerializer, ChainStatusSerializer, WalletSerializer


class ChainViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    serializer_class = ChainSerializer
    queryset = Chain.active.all()

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        chain = self.get_object()
        serializer = ChainStatusSerializer(chain, context={"request": request})
        return Response(serializer.data)


class WalletViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAdminUser,)
    serializer_class = WalletSerializer
    lookup_url_kwarg = "address"
    lookup_field = "address"

    def get_queryset(self) -> QuerySet:
        return BaseWallet.objects.all()
