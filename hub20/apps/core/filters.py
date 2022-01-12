from django.contrib.auth import get_user_model
from django.db.models import Q
from django_filters import rest_framework as filters

User = get_user_model()

from .models import Deposit


class UserFilter(filters.FilterSet):
    search = filters.CharFilter(label="search", method="user_suggestion")

    def user_suggestion(self, queryset, name, value):
        q_username = Q(username__istartswith=value)
        q_first_name = Q(first_name__istartswith=value)
        q_last_name = Q(last_name__istartswith=value)
        q_email = Q(email__istartswith=value)
        return queryset.filter(q_username | q_first_name | q_last_name | q_email)

    class Meta:
        model = User
        fields = ("search",)


class DepositFilter(filters.FilterSet):
    open = filters.BooleanFilter(label="open", method="filter_open")
    chain = filters.NumberFilter(field_name="currency__chain")
    token = filters.CharFilter(field_name="currency__address")

    def filter_open(self, queryset, name, value):
        return queryset.open() if value else queryset.expired()

    class Meta:
        model = Deposit
        fields = ("token", "chain", "open")
