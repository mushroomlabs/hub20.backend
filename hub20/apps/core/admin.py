import logging

from django.contrib import admin
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from . import forms, models

logger = logging.getLogger(__name__)


@admin.action(description="List selected tokens")
def accept(modeladmin, request, queryset):
    queryset.update(is_listed=True)


@admin.action(description="De-list selected tokens")
def reject(modeladmin, request, queryset):
    queryset.update(is_listed=False)


class TokenTypeListFilter(admin.SimpleListFilter):
    title = _("type")

    parameter_name = "type"

    def lookups(self, request, model_admin):
        return (
            ("erc20", "ERC20"),
            ("native", "Native"),
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection == "erc20":
            return queryset.exclude(address=models.Token.NULL_ADDRESS)
        elif selection == "native":
            return queryset.filter(address=models.Token.NULL_ADDRESS)
        else:
            return queryset


class TradeableTokenListFilter(admin.SimpleListFilter):
    title = _("tradeable")

    parameter_name = "tradeable"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Yes"),
            ("no", "No"),
        )

    def queryset(self, request, queryset):
        selection = self.value()

        logger.info(f"Selection is {type(selection)}: {selection}")

        if selection is None:
            return queryset

        tradeable_q = Q(chain__providers__is_active=True) & Q(is_listed=True)

        filter_type = queryset.filter if selection == "yes" else queryset.exclude
        return filter_type(tradeable_q)


class ConnectedChainTokenListFilter(admin.SimpleListFilter):
    title = _("connected chain")

    parameter_name = "connected_chain"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Yes"),
            ("no", "No"),
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        connected_q = Q(chain__providers__is_active=True)

        filter_type = queryset.filter if selection == "yes" else queryset.exclude
        return filter_type(connected_q)


class StableTokenListFilter(admin.SimpleListFilter):
    title = _("stable token")

    parameter_name = "stable"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Yes"),
            ("no", "No"),
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        stable_q = Q(stable_pair__isnull=False)

        filter_type = queryset.filter if selection == "yes" else queryset.exclude
        return filter_type(stable_q)


class FiatCurrencyListFilter(admin.SimpleListFilter):
    title = _("currency")

    parameter_name = "currency_code"

    def lookups(self, request, model_admin):
        return (
            (p.currency, p.get_currency_display)
            for p in models.StableTokenPair.objects.distinct("currency")
        )

    def queryset(self, request, queryset):
        currency = self.value()

        if currency:
            return queryset.filter(currency=currency)

        return queryset


@admin.register(models.Token)
class TokenAdmin(admin.ModelAdmin):
    form = forms.TokenForm

    search_fields = ["symbol", "name", "address", "chain__name"]
    list_display = ["symbol", "name", "address", "chain", "is_listed"]
    list_filter = (
        "is_listed",
        TokenTypeListFilter,
        TradeableTokenListFilter,
        ConnectedChainTokenListFilter,
        StableTokenListFilter,
    )
    readonly_fields = ["chain", "symbol", "name", "address", "decimals"]
    actions = [accept, reject]

    def has_add_permission(self, *args, **kw) -> bool:
        return False


@admin.register(models.TokenList)
class TokenListAdmin(admin.ModelAdmin):
    form = forms.TokenListForm
    list_display = ["name", "description"]


@admin.register(models.WrappedToken)
class WrappedTokenAdmin(admin.ModelAdmin):
    form = forms.WrappedTokenForm
    list_display = ("wrapped", "wrapper")


@admin.register(models.StableTokenPair)
class StableTokenPairAdmin(admin.ModelAdmin):
    form = forms.StableTokenPairForm

    list_display = ("token", "currency")
    list_filter = (FiatCurrencyListFilter,)
