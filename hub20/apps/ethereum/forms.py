from hub20.apps.core.forms import TokenForm

from .models import Erc20Token, NativeToken


class NativeTokenForm(TokenForm):
    class Meta:
        model = NativeToken
        fields = ("chain", "symbol", "name", "decimals", "logoURI", "is_listed")


class Erc20TokenForm(TokenForm):
    class Meta:
        model = Erc20Token
        fields = ("chain", "address", "symbol", "name", "decimals", "logoURI", "is_listed")
