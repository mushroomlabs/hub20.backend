from ethereum.utils import checksum_encode, normalize_address
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError


class AddressSerializerField(serializers.Field):
    """
    Ethereum address checksumed
    https://github.com/ethereum/EIPs/blob/master/EIPS/eip-55.md
    """

    def __init__(self, allow_zero_address=False, allow_sentinel_address=False, **kwargs):
        self.allow_zero_address = allow_zero_address
        self.allow_sentinel_address = allow_sentinel_address
        super().__init__(**kwargs)

    def to_representation(self, obj):
        return obj

    def to_internal_value(self, data):
        try:
            if int(data, 16) == 0 and not self.allow_zero_address:
                raise ValidationError("0x0 address is not allowed")
            elif int(data, 16) == 1 and not self.allow_sentinel_address:
                raise ValidationError("0x1 address is not allowed")

            return checksum_encode(normalize_address(int(data, 16)))
        except Exception:
            raise ValidationError("Address %s is not valid" % data)


# ================================================ #
#                Custom Fields
# ================================================ #
class HexadecimalField(serializers.Field):
    """
    Serializes hexadecimal values starting by `0x`. Empty values should be None or just `0x`.
    """

    default_error_messages = {
        "invalid": _("{value} is not an hexadecimal value."),
        "blank": _("This field may not be blank."),
        "max_length": _(
            "Ensure this field has no more than {max_length} hexadecimal chars (not counting 0x)."
        ),
        "min_length": _(
            "Ensure this field has at least {min_length} hexadecimal chars (not counting 0x)."
        ),
    }

    def __init__(self, **kwargs):
        self.allow_blank = kwargs.pop("allow_blank", False)
        self.max_length = kwargs.pop("max_length", None)
        self.min_length = kwargs.pop("min_length", None)
        super().__init__(**kwargs)

    def to_representation(self, obj):
        if not obj:
            return "0x"

        # We can get another types like `memoryview` from django models.
        # `to_internal_value` is not used when you provide an object
        # instead of a json using `data`. Make sure everything is HexBytes.
        if hasattr(obj, "hex"):
            obj = HexBytes(obj.hex())
        elif not isinstance(obj, HexBytes):
            obj = HexBytes(obj)
        return obj.hex()

    def to_internal_value(self, data):
        if isinstance(data, (bytes, memoryview)):
            data = data.hex()

        data = data.strip()  # Trim spaces
        if data.startswith("0x"):  # Remove 0x prefix
            data = data[2:]

        if not data:
            if self.allow_blank:
                return None
            else:
                self.fail("blank")

        data_len = len(data)
        if self.min_length and data_len < self.min_length:
            self.fail("min_length", min_length=data_len)
        elif self.max_length and data_len > self.max_length:
            self.fail("max_length", max_length=data_len)

        try:
            return HexBytes(data)
        except ValueError:
            self.fail("invalid", value=data)


class Sha3HashField(HexadecimalField):
    def __init__(self, **kwargs):
        kwargs["max_length"] = 64
        kwargs["min_length"] = 64
        super().__init__(**kwargs)
