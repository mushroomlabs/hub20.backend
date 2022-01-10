from typing import Any

from django.db import models

from .validators import token_logo_uri_validator


class TokenLogoURLField(models.URLField):
    default_validators = [token_logo_uri_validator]


class EthereumTokenAmountField(models.DecimalField):
    def __init__(self, *args: Any, **kw: Any) -> None:
        kw.setdefault("decimal_places", 18)
        kw.setdefault("max_digits", 32)

        super().__init__(*args, **kw)
