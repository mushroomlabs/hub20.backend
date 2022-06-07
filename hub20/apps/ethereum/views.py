from django.db.models import Q
from django.db.models.query import QuerySet
from django_filters import rest_framework as filters
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from hub20.apps.core.views.tokens import BaseTokenFilter

from .models import BaseWallet, Chain
from .serializers import ChainSerializer, ChainStatusSerializer, WalletSerializer


class EthereumTokenFilter(BaseTokenFilter):
    chain_id = filters.ModelChoiceFilter(queryset=Chain.active.all())
    native = filters.BooleanFilter(label="native", method="filter_native")

    def token_search(self, queryset, name, value):
        q_name = Q(name__istartswith=value)
        q_symbol = Q(symbol__iexact=value)
        return queryset.filter(q_name | q_symbol)

    def filter_native(self, queryset, name, value):
        return queryset.exclude(nativetoken__isnull=value)

    class Meta:
        model = BaseTokenFilter.Meta.model
        ordering_fields = ("symbol",)
        fields = ("symbol", "native", "stable_tokens", "fiat")


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
