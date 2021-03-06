from typing import Optional

from django.contrib import admin
from django.db.models import Q
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from hub20.apps.core.admin import (
    StableTokenListFilter,
    TradeableTokenListFilter,
    accept,
    activate_provider,
    deactivate_provider,
    reject,
)

from . import models
from .forms import Erc20TokenForm, NativeTokenForm, Web3ProviderForm
from .models import EthereumAccount_T


class ConnectedChainListFilter(admin.SimpleListFilter):
    title = _("connected chain")

    parameter_name = "connected"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Yes"),
            ("no", "No"),
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        connected_q = Q(blockchainpaymentnetwork__providers__is_active=True)

        filter_type = queryset.filter if selection == "yes" else queryset.exclude
        return filter_type(connected_q)


class TestChainListFilter(admin.SimpleListFilter):
    title = _("testnets of")

    parameter_name = "testnet"

    def lookups(self, request, model_admin):
        return (
            models.Chain.objects.filter(testnets__isnull=False)
            .distinct()
            .values_list("id", "name")
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        return models.Chain.objects.filter(info__testing_for=selection)


class RollupListFilter(admin.SimpleListFilter):
    title = _("rollups for")

    parameter_name = "rollup"

    def lookups(self, request, model_admin):
        return (
            models.Chain.objects.filter(rollups__isnull=False).distinct().values_list("id", "name")
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        return models.Chain.objects.filter(info__rollup_for=selection)


class SidechainListFilter(admin.SimpleListFilter):
    title = _("sidechains")

    parameter_name = "sidechain"

    def lookups(self, request, model_admin):
        return (
            models.Chain.objects.filter(sidechains__isnull=False)
            .distinct()
            .values_list("id", "name")
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        return models.Chain.objects.filter(info__sidechain_for=selection)


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

        connected_q = Q(chain__blockchainpaymentnetwork__providers__is_active=True)

        filter_type = queryset.filter if selection == "yes" else queryset.exclude
        return filter_type(connected_q)


class ChainFilter(admin.SimpleListFilter):
    title = _("chain")

    parameter_name = "chain"

    def lookups(self, request, model_admin):
        return (
            models.Chain.objects.filter(tokens__isnull=False).distinct().values_list("id", "name")
        )

    def queryset(self, request, queryset):
        selection = self.value()

        if selection is None:
            return queryset

        return queryset.filter(chain_id=selection)


class ChainMetadataInline(admin.StackedInline):
    model = models.ChainMetadata
    autocomplete_fields = ("testing_for", "rollup_for", "sidechain_for")
    fields = ("short_name", "testing_for", "rollup_for", "sidechain_for")
    fk_name = "chain"


@admin.register(models.Chain)
class ChainAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "id", "provider")
    list_filter = (
        ConnectedChainListFilter,
        TestChainListFilter,
        RollupListFilter,
        SidechainListFilter,
    )
    readonly_fields = ("highest_block",)
    search_fields = ("name", "id")

    inlines = [ChainMetadataInline]


@admin.register(models.Web3Provider)
class Web3ProviderAdmin(admin.ModelAdmin):
    form = Web3ProviderForm

    list_display = (
        "hostname",
        "network",
        "is_active",
        "connected",
        "synced",
    )
    autocomplete_fields = ("network",)
    list_filter = ("is_active", "connected", "synced")
    readonly_fields = ("network", "connected", "synced")
    search_fields = (
        "url",
        "network__name",
        "network__blockchainpaymentnetwork__chain__name",
    )

    actions = [activate_provider, deactivate_provider]


@admin.register(models.Explorer)
class BlockchainExplorerAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "standard")
    list_filter = ("standard",)
    search_fields = ("url", "chain__name")


@admin.register(models.NativeToken)
class NativeTokenAdmin(admin.ModelAdmin):
    form = NativeTokenForm

    search_fields = ["symbol", "name", "chain__name"]
    list_display = ["symbol", "name", "chain", "is_listed"]
    list_filter = (
        "is_listed",
        TradeableTokenListFilter,
        ConnectedChainListFilter,
        StableTokenListFilter,
    )
    readonly_fields = ["chain", "symbol", "name", "address", "decimals"]
    actions = [accept, reject]

    def has_add_permission(self, *args, **kw) -> bool:
        return False


@admin.register(models.Erc20Token)
class Erc20TokenAdmin(admin.ModelAdmin):
    form = Erc20TokenForm

    search_fields = ["symbol", "name", "address", "chain__name"]
    list_display = ["symbol", "name", "address", "chain", "is_listed"]
    list_filter = (
        "is_listed",
        ChainFilter,
        TradeableTokenListFilter,
        ConnectedChainTokenListFilter,
        StableTokenListFilter,
    )
    readonly_fields = ["chain", "symbol", "name", "address", "decimals"]
    actions = [accept, reject]

    def has_add_permission(self, *args, **kw) -> bool:
        return False


@admin.register(models.BlockchainPaymentNetwork)
class BlockchainPaymentNetworkAdmin(admin.ModelAdmin):
    search_fields = ("name", "chain__name")


@admin.register(models.BaseWallet)
class EthereumAccountAdmin(admin.ModelAdmin):
    list_display = ("address",)

    def has_add_permission(
        self, request: HttpRequest, obj: Optional[EthereumAccount_T] = None
    ) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Optional[EthereumAccount_T] = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Optional[EthereumAccount_T] = None
    ) -> bool:
        return False
