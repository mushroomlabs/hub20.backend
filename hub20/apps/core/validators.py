from urllib.parse import urlparse

from django.core.exceptions import ValidationError


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


tokenlist_uri_validator = uri_parsable_scheme_validator(("https", "http", "ipfs", "ens"))
