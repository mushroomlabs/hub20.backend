from django.db.models import BooleanField, Case, Q, Value, When
from django.db.models.query import QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from eth_utils import is_address
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from hub20.apps.blockchain.models import Chain

from . import models, serializers, tasks


class TokenFilter(filters.FilterSet):
    chain_id = filters.ModelChoiceFilter(queryset=Chain.active.all())
    listed = filters.BooleanFilter(label="listed", method="filter_listed")
    native = filters.BooleanFilter(label="native", method="filter_native")
    stable_tokens = filters.BooleanFilter(label="stable", method="filter_stable_tokens")
    fiat = filters.CharFilter(label="fiat", method="filter_fiat")

    def token_search(self, queryset, name, value):
        q_name = Q(name__istartswith=value)
        q_symbol = Q(symbol__iexact=value)
        q_chain_name = Q(chain__name__icontains=value)
        return queryset.filter(q_name | q_symbol | q_chain_name)

    def filter_listed(self, queryset, name, value):
        return queryset.exclude(ethereum_money_tokenlist_tokenlists__isnull=value)

    def filter_native(self, queryset, name, value):
        filtered_qs = queryset.filter if value else queryset.exclude
        return filtered_qs(address=models.EthereumToken.NULL_ADDRESS)

    def filter_stable_tokens(self, queryset, name, value):
        return queryset.exclude(stable_pair__token__isnull=value)

    def filter_fiat(self, queryset, name, value):
        return queryset.filter(stable_pair__currency__iexact=value)

    class Meta:
        model = models.EthereumToken
        ordering_fields = ("symbol", "chain_id")
        fields = ("chain_id", "symbol", "address", "listed", "native", "stable_tokens", "fiat")


class BaseTokenViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    serializer_class = serializers.HyperlinkedEthereumTokenSerializer
    filterset_class = TokenFilter
    filter_backends = (
        OrderingFilter,
        SearchFilter,
        filters.DjangoFilterBackend,
    )
    page_size = 50
    search_fields = ("name", "=symbol", "chain__name")
    ordering_fields = ("symbol", "name", "chain_id")
    ordering = ("-is_native", "chain_id", "symbol")

    def get_queryset(self) -> QuerySet:
        return models.EthereumToken.tradeable.annotate(
            is_native=Case(
                When(address=models.EthereumToken.NULL_ADDRESS, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

    def get_object(self):
        address = self.kwargs["address"]
        if not is_address(address):
            raise Http404(f"{address} is not a valid token address")

        return get_object_or_404(
            models.EthereumToken, chain_id=self.kwargs["chain_id"], address=address
        )


class TokenViewSet(BaseTokenViewSet):
    def get_serializer_class(self):
        if self.action == "info":
            return serializers.TokenInfoSerializer
        return self.serializer_class

    @action(detail=True)
    def info(self, request, **kwargs):
        """
        Returns extra information that the hub operator has provided about this token.
        """
        token = self.get_object()
        serializer = self.get_serializer(instance=token)
        return Response(serializer.data)


class TokenListViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    """
    Token lists (https://tokenlists.org) is community-led effort to
    curate lists of ERC20 tokens. Hub Operators can create their own
    token lists, and its users can choose freely which ones to use.
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.TokenListSerializer
    queryset = models.TokenList.objects.all()

    def get_serializer_class(self):
        if self.action == "_import":
            return serializers.TokenListImportSerializer

        return serializers.TokenListSerializer

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        name="Import from URL",
        permission_classes=(IsAdminUser,),
    )
    def _import(self, request, **kwargs):
        """
        Fetches, validates and imports the token list from the
        provided URL. This process is executed on the background
        """
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            tasks.import_token_list.delay(
                url=serializer.validated_data["url"],
                description=serializer.validated_data["description"],
            )
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserTokenListViewSet(ModelViewSet):

    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.UserTokenListSerializer

    def get_queryset(self):
        return self.request.user.token_lists.all()

    def get_serializer_class(self):
        if self.action == "clone":
            return serializers.UserTokenListCloneSerializer
        return serializers.UserTokenListSerializer

    @action(detail=False, methods=["post"])
    def clone(self, request, **kwargs):
        """
        Clone a token list from the site's base, allowing users to
        create their own token lists
        """
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
