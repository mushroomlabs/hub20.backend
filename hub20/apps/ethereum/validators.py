from django.core.exceptions import ValidationError
from web3 import Web3

from hub20.apps.core.validators import uri_parsable_scheme_validator


def validate_checksumed_address(address):
    try:
        if not Web3.isChecksumAddress(address):
            raise ValidationError(
                "%(address)s has an invalid checksum",
                params={"address": address},
            )
    except Exception:
        raise ValidationError(
            "%(address)s is not a valid ethereum address",
            params={"address": address},
        )


web3_url_validator = uri_parsable_scheme_validator(("http", "https", "ws", "wss", "ipc"))
