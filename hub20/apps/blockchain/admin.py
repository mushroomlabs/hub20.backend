from typing import Optional

from django import forms
from django.contrib import admin
from django.db.models import Q
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from . import models
from .typing import EthereumAccount_T
from .validators import web3_url_validator


class ConnectedChainTokenListFilter(admin.SimpleListFilter):
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

        connected_q = Q(providers__is_active=True)

        filter_type = queryset.filter if selection == "yes" else queryset.exclude
        return filter_type(connected_q)


class Web3URLField(forms.URLField):
    default_validators = [web3_url_validator]


Web3ProviderForm = forms.modelform_factory(
    model=models.Web3Provider,
    fields=["chain", "url", "is_active", "connected", "synced"],
    field_classes={"url": Web3URLField},
)


@admin.register(models.Chain)
class ChainAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_mainnet", "provider")
    list_filter = ("is_mainnet", ConnectedChainTokenListFilter)
    readonly_fields = ("highest_block",)
    search_fields = ("name", "id")


@admin.register(models.Web3Provider)
class Web3ProviderAdmin(admin.ModelAdmin):
    form = Web3ProviderForm

    list_display = ("hostname", "chain", "is_active", "connected", "synced")
    list_filter = ("is_active", "connected", "synced")
    readonly_fields = ("connected", "synced")
    search_fields = ("url", "chain__name")


@admin.register(models.Explorer)
class BlockchainExplorerAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "standard")
    list_filter = ("standard",)


@admin.register(models.BaseEthereumAccount)
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
