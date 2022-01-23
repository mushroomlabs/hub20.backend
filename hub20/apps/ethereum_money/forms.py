from django import forms

from . import models, validators

TOKEN_FILTER_QS = models.EthereumToken.tradeable.all()


class TokenlistStandardURLField(forms.URLField):
    default_validators = [validators.tokenlist_uri_validator]


class TokenForm(forms.ModelForm):
    logoURI = TokenlistStandardURLField(required=False)

    class Meta:
        model = models.EthereumToken
        fields = ("chain", "address", "symbol", "name", "decimals", "logoURI", "is_listed")


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


class StableTokenPairForm(forms.ModelForm):
    token = forms.ModelChoiceField(queryset=TOKEN_FILTER_QS)

    class Meta:
        model = models.StableTokenPair
        fields = ("token", "currency", "algorithmic_peg")
