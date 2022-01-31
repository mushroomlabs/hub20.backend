from typing import Any

from django.db import models

from .validators import tokenlist_uri_validator


class TokenlistStandardURLField(models.URLField):
    default_validators = [tokenlist_uri_validator]


class EthereumTokenAmountField(models.DecimalField):
    def __init__(self, *args: Any, **kw: Any) -> None:
        kw.setdefault("decimal_places", 18)
        kw.setdefault("max_digits", 32)

        super().__init__(*args, **kw)
