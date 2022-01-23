from typing import Optional

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from . import models
from .typing import EthereumAccount_T
from .validators import web3_url_validator


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
    list_filter = ("is_mainnet",)
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
