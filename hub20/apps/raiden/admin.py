from typing import Any, Optional

from django.contrib import admin
from django.http import HttpRequest

from . import forms, models


class ReadOnlyModelAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest, obj: Optional[Any] = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Optional[Any] = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Any] = None) -> bool:
        return False


@admin.register(models.Raiden)
class RaidenAdmin(admin.ModelAdmin):
    form = forms.RaidenForm
    list_display = ("url", "address", "web3_provider", "chain")
    fields = (
        "url",
        "web3_provider",
        "address",
    )
    readonly_fields = ("address",)

    def has_add_permission(self, request: HttpRequest, obj: Optional[Any] = None) -> bool:
        return request.user.is_superuser


@admin.register(models.TokenNetwork)
class TokenNetworkAdmin(ReadOnlyModelAdmin):
    list_display = ("token", "address")


@admin.register(models.Payment)
class PaymentAdmin(ReadOnlyModelAdmin):
    list_display = ("channel", "token", "amount", "timestamp", "identifier", "sender_address")
