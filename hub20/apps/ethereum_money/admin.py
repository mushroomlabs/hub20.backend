from django.contrib import admin

from . import forms, models


@admin.register(models.EthereumToken)
class TokenAdmin(admin.ModelAdmin):
    form = forms.TokenForm

    search_fields = ["symbol", "name", "address", "chain__name"]
    list_display = ["symbol", "name", "address", "chain", "is_listed"]
    list_filter = ["is_listed", "chain"]
    readonly_fields = ["chain", "symbol", "name", "address", "decimals"]


# @admin.register(models.TokenList)
# class TokenListAdmin(admin.ModelAdmin):
#     form = forms.TokenListForm
#     list_display = ["name", "description"]


@admin.register(models.WrappedToken)
class WrappedTokenAdmin(admin.ModelAdmin):
    form = forms.WrappedTokenForm

    list_display = ("wrapped", "wrapper")


@admin.register(models.StableTokenPair)
class StableTokenPairAdmin(admin.ModelAdmin):
    form = forms.StableTokenPairForm

    list_display = ("token", "currency")
    list_filter = ("currency",)
