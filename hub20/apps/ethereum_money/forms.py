from django import forms

from . import models

TOKEN_FILTER_QS = models.EthereumToken.objects.filter(chain__providers__is_active=True)


class TokenListForm(forms.ModelForm):
    tokens = forms.ModelMultipleChoiceField(queryset=TOKEN_FILTER_QS)

    class Meta:
        model = models.TokenList
        fields = ("name", "description", "tokens")


class WrappedTokenForm(forms.ModelForm):
    wrapped = forms.ModelChoiceField(queryset=TOKEN_FILTER_QS)
    wrapper = forms.ModelChoiceField(queryset=TOKEN_FILTER_QS)

    class Meta:
        model = models.WrappedToken
        fields = ("wrapped", "wrapper")
