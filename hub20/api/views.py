from django.db.models import BooleanField, Case, Value, When
from django.db.models.query import QuerySet
from django.http import Http404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse, reverse_lazy
from rest_framework.views import APIView

from hub20.apps.core.models import PaymentNetwork
from hub20.apps.core.serializers.accounting import HyperlinkedTokenBalanceSerializer
from hub20.apps.core.serializers.tokens import TokenSerializer
from hub20.apps.core.views.tokens import BaseTokenViewSet
from hub20.apps.ethereum.filters import EthereumTokenFilter

from . import VERSION, serializers


class IndexView(APIView):
    """
    Hub20 Root Endpoint. Provides links to other endpoints and informs version for clients.
    """

    permission_classes = (AllowAny,)

    def get(self, request, **kw):
        return Response(
            {
                "current_user_url": reverse_lazy("rest_user_details", request=request),
                "networks_url": reverse_lazy("network-list", request=request),
                "accounting_report_url": reverse_lazy("accounting-report", request=request),
                "tokens_url": reverse_lazy("token-list", request=request),
                "users_url": reverse_lazy("users-list", request=request),
                "version": VERSION,
            }
        )


class TokenBrowserViewSet(BaseTokenViewSet):
    filterset_class = EthereumTokenFilter
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
        Returns estimated cost in Wei to execute a transfer on all networks that support the token

        """
        token = self.get_object()

        transfer_costs = {}

        for network in PaymentNetwork.objects.select_subclasses():
            if not network.supports_token(token):
                continue

            network_url = reverse("network-detail", kwargs={"pk": network.pk}, request=request)
            for provider in network.providers(manager="available").select_subclasses():
                if (transfer_cost := provider.get_transfer_fee_estimate(token)) is not None:
                    transfer_costs[network_url] = transfer_cost.as_wei
                    continue
        try:
            return Response(transfer_costs)
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
