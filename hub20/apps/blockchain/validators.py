from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from ethereum.utils import check_checksum


def validate_checksumed_address(address):
    try:
        if not check_checksum(address):
            raise ValidationError(
                "%(address)s has an invalid checksum",
                params={"address": address},
            )
    except Exception:
        raise ValidationError(
            "%(address)s is not a valid ethereum address",
            params={"address": address},
        )


def uri_parsable_scheme_validator(schemes):
    def decorator(url):
        parsed = urlparse(url)

        errors = []

        if parsed.scheme not in schemes:
            errors.append(
                ValidationError(
                    "Scheme %(value)s is not acceptable",
                    code="required",
                    params=dict(value=parsed.scheme),
                )
            )

        if not parsed.netloc:
            errors.append(
                ValidationError(
                    "Could not find host/location for %(value)s ",
                    code="required",
                    params=dict(value=url),
                )
            )

        if errors:
            raise ValidationError(errors)

    return decorator


web3_url_validator = uri_parsable_scheme_validator(("http", "https", "ws", "wss", "ipc"))
