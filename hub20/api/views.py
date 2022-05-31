from django.db.models import BooleanField, Case, Q, Value, When
from django.db.models.query import QuerySet
from django.http import Http404
from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse_lazy
from rest_framework.views import APIView

from hub20.apps.core.serializers.accounting import HyperlinkedTokenBalanceSerializer
from hub20.apps.core.serializers.tokens import TokenSerializer
from hub20.apps.core.views.tokens import BaseTokenFilter, BaseTokenViewSet
from hub20.apps.ethereum.client import get_estimate_fee
from hub20.apps.ethereum.models import Chain

from . import VERSION, serializers

RAIDEN_DESCRIPTION = "Enables instant and ultra-cheap transfers of ERC20 tokens"


class TokenFilter(BaseTokenFilter):
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


class IndexView(APIView):
    """
    Hub20 Root Endpoint. Provides links to other endpoints and informs version for clients.
    """

    permission_classes = (AllowAny,)

    def get(self, request, **kw):
        return Response(
            {
                "current_user_url": reverse_lazy("rest_user_details", request=request),
                "blockchains_url": reverse_lazy("blockchain:chain-list", request=request),
                "accounting_report_url": reverse_lazy("accounting-report", request=request),
                "tokens_url": reverse_lazy("token-list", request=request),
                "users_url": reverse_lazy("users-list", request=request),
                "version": VERSION,
            }
        )


class NetworkIndexView(APIView):
    """
    Description of all payment networks supported by this hub
    """

    permission_classes = (AllowAny,)

    def get(self, request, **kw):
        active_chains = Chain.active.all()
        return Response(
            {
                "blockchains": [
                    dict(name=c.name, code=c.short_name, id=c.id) for c in active_chains
                ],
                "offchain": [dict(name="Raiden", code="raiden", description=RAIDEN_DESCRIPTION)],
            }
        )


class TokenBrowserViewSet(BaseTokenViewSet):
    search_fields = ("name", "=symbol", "nativetoken__chain__name", "erc20token__chain__name")
    ordering_fields = ("symbol", "name")
    ordering = ("-is_native", "symbol")

    def get_serializer_class(self):
        if self.action == "balance":
            return HyperlinkedTokenBalanceSerializer
        elif self.action == "routes":
            return serializers.TokenRouteDescriptorSerializer
        elif self.action == "retrieve":
            token_model = type(self.get_object())
            serializer_classes = TokenSerializer.__subclasses__()
            return {s.Meta.model: s for s in serializer_classes}.get(token_model, TokenSerializer)
        else:
            return super().get_serializer_class()

    def get_queryset(self) -> QuerySet:
        qs = super().get_queryset()
        return qs.annotate(
            is_native=Case(
                When(nativetoken__isnull=False, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

    @action(detail=True)
    def transfer_cost(self, request, **kwargs):
        """
        Returns estimated cost in Wei (estimated gas * gas price) to execute a transfer

        Returns 404 if not connected to the blockchain or if token not in database
        """
        token = self.get_object()
        try:
            transfer_cost = get_estimate_fee(w3=token.chain.provider.w3, token=token)
            return Response(transfer_cost.as_wei)
        except AttributeError:
            raise Http404
        except TypeError:
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @action(detail=True, permission_classes=(IsAuthenticated,))
    def balance(self, request, **kwargs):
        """
        Returns user balance for that token
        """
        try:
            token = self.get_object()
            balance = self.request.user.account.get_balance(token)
            serializer = self.get_serializer(instance=balance)
            return Response(serializer.data)
        except AttributeError:
            raise Http404

    @action(detail=True)
    def routes(self, request, **kwargs):
        """
        Returns list of all routes that can be used for deposits/withdrawals in the hub
        """
        token = self.get_object()
        serializer = self.get_serializer(instance=token)
        return Response(serializer.data)
