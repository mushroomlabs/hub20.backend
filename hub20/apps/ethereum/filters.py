from django.db.models import Q
from django_filters import rest_framework as filters

from hub20.apps.core.views.tokens import BaseTokenFilter

from .models import Chain


class EthereumTokenFilter(BaseTokenFilter):
    chain_id = filters.ModelChoiceFilter(label="chain", queryset=Chain.active.distinct())
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
        fields = ("symbol", "native", "stable_tokens", "fiat", "chain_id")
