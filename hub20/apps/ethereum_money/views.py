from django.db.models import BooleanField, Case, Q, Value, When
from django.db.models.query import QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from eth_utils import is_address
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from . import models, serializers
from .permissions import IsTokenListOwner


class TokenFilter(filters.FilterSet):
    listed = filters.BooleanFilter(label="listed", method="filter_listed")
    native = filters.BooleanFilter(label="native", method="filter_native")

    def token_search(self, queryset, name, value):
        q_name = Q(name__istartswith=value)
        q_symbol = Q(symbol__iexact=value)
        q_chain_name = Q(chain__name__icontains=value)
        return queryset.filter(q_name | q_symbol | q_chain_name)

    def filter_listed(self, queryset, name, value):
        return queryset.exclude(usertokenlist__isnull=value)

    def filter_native(self, queryset, name, value):
        filtered_qs = queryset.filter if value else queryset.exclude
        return filtered_qs(address=models.EthereumToken.NULL_ADDRESS)

    class Meta:
        model = models.EthereumToken
        ordering_fields = ("symbol", "chain_id")
        fields = ("chain_id", "symbol", "address", "listed", "native")


class TokenViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
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
        return models.EthereumToken.objects.annotate(
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

    @action(detail=True)
    def wrappers(self, request, **kwargs):
        """
        Returns list of tokens that are wrap a native token into
        ERC20 or bridge them to another chain
        """
        token = self.get_object()
        wrapper_tokens = models.EthereumToken.objects.filter(wrappedtoken__wrapped=token)

        page = self.paginate_queryset(wrapper_tokens)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(wrapper_tokens, many=True)
        return Response(serializer.data)


class UserTokenListViewSet(ModelViewSet):
    permission_classes = (IsTokenListOwner,)
    serializer_class = serializers.UserTokenListSerializer

    def get_queryset(self) -> QuerySet:
        return self.request.user.token_lists.all()

    def get_object(self, *args, **kw):
        token_list = get_object_or_404(models.UserTokenList, id=self.kwargs["pk"])
        self.check_object_permissions(self.request, token_list)
        return token_list
