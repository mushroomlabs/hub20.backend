import logging

from django.contrib import admin
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from . import forms, models

logger = logging.getLogger(__name__)


@admin.action(description="Activate selected providers")
def activate_provider(modeladmin, request, queryset):
    for provider in queryset.select_subclasses():
        provider.activate()


@admin.action(description="De-activate selected providers")
def deactivate_provider(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.action(description="List selected tokens")
def accept(modeladmin, request, queryset):
    queryset.update(is_listed=True)


@admin.action(description="De-list selected tokens")
def reject(modeladmin, request, queryset):
    queryset.update(is_listed=False)


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

        tradeable_q = Q(is_listed=True)

        filter_type = queryset.filter if selection == "yes" else queryset.exclude
        return filter_type(tradeable_q)


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


@admin.register(models.BaseToken)
class BaseTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "is_listed")
    search_fields = ("name", "symbol")
    list_filter = ("is_listed",)


@admin.register(models.TokenList)
class TokenListAdmin(admin.ModelAdmin):
    form = forms.TokenListForm
    list_display = ("name", "description")


@admin.register(models.WrappedToken)
class WrappedTokenAdmin(admin.ModelAdmin):
    form = forms.WrappedTokenForm
    list_display = ("wrapped", "wrapper")


@admin.register(models.StableTokenPair)
class StableTokenPairAdmin(admin.ModelAdmin):
    form = forms.StableTokenPairForm

    list_display = ("token", "currency")
    list_filter = (FiatCurrencyListFilter,)
    autocomplete_fields = ("token",)


@admin.register(models.PaymentNetwork)
class PaymentNetworkAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(models.PaymentNetworkProvider)
class PaymentNetworkProviderAdmin(admin.ModelAdmin):
    list_display = ("network", "is_active", "connected", "synced")
    list_filter = ("is_active", "connected", "synced")
    search_fields = ("network__name",)
