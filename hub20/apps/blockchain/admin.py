from typing import Optional

from django.contrib import admin
from django.http import HttpRequest

from .models import BaseEthereumAccount
from .typing import EthereumAccount_T


@admin.register(BaseEthereumAccount)
class EthereumAccountAdmin(admin.ModelAdmin):
    list_display = ["address"]

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
