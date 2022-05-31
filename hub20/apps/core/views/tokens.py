from django.db.models import Q
from django.db.models.query import QuerySet
from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from .. import models, serializers


class BaseTokenFilter(filters.FilterSet):
    stable_tokens = filters.BooleanFilter(label="stable", method="filter_stable_tokens")
    fiat = filters.CharFilter(label="fiat", method="filter_fiat")

    def token_search(self, queryset, name, value):
        q_name = Q(name__istartswith=value)
        q_symbol = Q(symbol__iexact=value)
        return queryset.filter(q_name | q_symbol)

    def filter_stable_tokens(self, queryset, name, value):
        return queryset.exclude(stable_pair__token__isnull=value)

    def filter_fiat(self, queryset, name, value):
        return queryset.filter(stable_pair__currency__iexact=value)

    class Meta:
        model = models.BaseToken
        ordering_fields = ("symbol",)
        fields = ("symbol", "stable_tokens", "fiat")


class BaseTokenViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    serializer_class = serializers.HyperlinkedTokenSerializer
    filterset_class = BaseTokenFilter
    filter_backends = (
        OrderingFilter,
        SearchFilter,
        filters.DjangoFilterBackend,
    )
    page_size = 50
    search_fields = ("name", "=symbol")
    ordering_fields = ("symbol", "name")
    ordering = ("symbol",)
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self) -> QuerySet:
        return models.BaseToken.tradeable.select_subclasses()

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
