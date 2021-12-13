from django import forms
from django.contrib import admin

from . import models
from .validators import token_logo_uri_validator


class TokenLogoURLField(forms.URLField):
    default_validators = [token_logo_uri_validator]


TokenForm = forms.modelform_factory(
    model=models.EthereumToken,
    fields=["chain", "address", "symbol", "name", "decimals", "logoURI", "is_listed"],
    field_classes={"logoURI": TokenLogoURLField},
)


@admin.register(models.EthereumToken)
class TokenAdmin(admin.ModelAdmin):
    form = TokenForm

    search_fields = ["symbol", "name", "address", "chain__name"]
    list_display = ["symbol", "name", "address", "chain", "is_listed"]
    list_filter = ["is_listed", "chain"]
    readonly_fields = ["chain", "symbol", "name", "address", "decimals"]
