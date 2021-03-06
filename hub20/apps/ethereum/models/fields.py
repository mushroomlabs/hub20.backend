from django.db import connection, models
from django.utils.translation import gettext_lazy as _
from hexbytes import HexBytes
from web3 import Web3

from ..validators import validate_checksumed_address, web3_url_validator


class Web3ProviderURLField(models.URLField):
    default_validators = [web3_url_validator]


class EthereumAddressField(models.CharField):
    default_validators = [validate_checksumed_address]
    description = _("Ethereum Address")

    def __init__(self, *args, **kwargs):
        kwargs["max_length"] = 42
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["max_length"]
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        value = super().to_python(value)
        return value and Web3.toChecksumAddress(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return value and Web3.toChecksumAddress(value)


class Uint256Field(models.DecimalField):
    """
    Field to store ethereum uint256 values. Uses Decimal db type without
    decimals to store in the database, but retrieve as `int` instead of
    `Decimal` (https://docs.python.org/3/library/decimal.html)
    """

    description = _("Ethereum uint256 number")

    def __init__(self, *args, **kwargs):
        kwargs["max_digits"] = 79  # 2 ** 256 is 78 digits
        kwargs["decimal_places"] = 0
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["max_digits"]
        del kwargs["decimal_places"]
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return int(value)


class HexField(models.CharField):
    """
    Field to store hex values (without 0x). Returns hex with 0x prefix.

    On Database side a CharField is used.
    """

    description = "Stores a hex value into an CharField"

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        return value if value is None else HexBytes(value).hex()

    def get_prep_value(self, value):
        if value is None:
            return value
        elif isinstance(value, HexBytes):
            return value.hex()[2:]  # HexBytes.hex() retrieves hexadecimal with '0x', remove it
        elif isinstance(value, bytes):
            return value.hex()  # bytes.hex() retrieves hexadecimal without '0x'
        else:  # str
            return HexBytes(value).hex()[2:]

    def formfield(self, **kwargs):
        # We need max_length + 2 on forms because of `0x`
        defaults = {"max_length": self.max_length + 2}
        # TODO: Handle multiple backends with different feature flags.
        if self.null and not connection.features.interprets_empty_strings_as_nulls:
            defaults["empty_value"] = None
        defaults.update(kwargs)
        return super().formfield(**defaults)

    def clean(self, value, model_instance):
        value = self.to_python(value)
        self.validate(value, model_instance)
        # Validation didn't work because of `0x`
        self.run_validators(value[2:])
        return value


class Sha3HashField(HexField):
    def __init__(self, *args, **kwargs):
        kwargs["max_length"] = 64
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["max_length"]
        return name, path, args, kwargs


__all__ = [
    "Web3ProviderURLField",
    "EthereumAddressField",
    "Uint256Field",
    "HexField",
    "Sha3HashField",
]
