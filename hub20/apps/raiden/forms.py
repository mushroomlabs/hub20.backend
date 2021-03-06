from django import forms

from hub20.apps.ethereum.models import Chain
from hub20.apps.ethereum.validators import uri_parsable_scheme_validator

from . import models

raiden_url_validator = uri_parsable_scheme_validator(("http", "https"))


class RaidenURLField(forms.URLField):
    default_validators = [raiden_url_validator]


class RaidenForm(forms.ModelForm):
    url = RaidenURLField()
    chain = forms.ModelChoiceField(queryset=Chain.active.distinct())

    class Meta:
        model = models.Raiden
        fields = ("url", "address", "chain")
