from django import forms

from . import models


class TokenListForm(forms.ModelForm):
    tokens = forms.ModelMultipleChoiceField(
        queryset=models.EthereumToken.objects.filter(chain__providers__is_active=True).all()
    )

    class Meta:
        model = models.TokenList
        fields = ("name", "description", "tokens")
