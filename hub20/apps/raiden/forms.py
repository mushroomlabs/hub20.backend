from django import forms

from hub20.apps.blockchain.models import Web3Provider
from hub20.apps.blockchain.validators import uri_parsable_scheme_validator

from . import models

raiden_url_validator = uri_parsable_scheme_validator(("http", "https"))


class RaidenURLField(forms.URLField):
    default_validators = [raiden_url_validator]


class RaidenForm(forms.ModelForm):
    url = RaidenURLField()
    web3_provider = forms.ModelChoiceField(queryset=Web3Provider.available.all())

    class Meta:
        model = models.Raiden
        fields = ("url", "web3_provider")
