from django import forms

from hub20.apps.blockchain.models import Chain
from hub20.apps.blockchain.validators import uri_parsable_scheme_validator

from . import models
from .client.node import RaidenClient
from .exceptions import RaidenConnectionError

raiden_url_validator = uri_parsable_scheme_validator(("http", "https"))


class RaidenURLField(forms.URLField):
    default_validators = [raiden_url_validator]


class RaidenForm(forms.ModelForm):
    url = RaidenURLField()
    chain = forms.ModelChoiceField(queryset=Chain.active.all())

    def clean(self):
        try:
            raiden_url = self.cleaned_data["url"]
            RaidenClient.get_node_account_address(raiden_url)
        except RaidenConnectionError:
            raise forms.ValidationError(f"Could not connect to {raiden_url}")
        return self.cleaned_data

    class Meta:
        model = models.Raiden
        fields = ("url", "chain")
