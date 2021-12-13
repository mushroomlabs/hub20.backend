from django.contrib import admin

from . import models


@admin.register(models.EthereumToken)
class TokenAdmin(admin.ModelAdmin):
    search_fields = ["symbol", "name", "address", "chain__name"]
    list_display = ["symbol", "name", "address", "chain", "is_listed"]
    list_filter = ["is_listed", "chain"]
