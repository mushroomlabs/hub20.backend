from typing import Any, Optional

from django.contrib import admin
from django.http import HttpRequest

from . import forms, models
from .client.node import RaidenClient


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
    list_display = ("url", "account", "chain")
    fields = (
        "url",
        "chain",
    )
    readonly_fields = ("account",)

    def save_form(self, request, form, change):
        return RaidenClient.make_raiden(**form.cleaned_data)

    def save_related(self, request, form, formsets, change):
        pass

    def has_add_permission(self, request: HttpRequest, obj: Optional[Any] = None) -> bool:
        return request.user.is_superuser


@admin.register(models.TokenNetwork)
class TokenNetworkAdmin(ReadOnlyModelAdmin):
    list_display = ("token", "address")


@admin.register(models.Payment)
class PaymentAdmin(ReadOnlyModelAdmin):
    list_display = ("channel", "token", "amount", "timestamp", "identifier", "sender_address")
