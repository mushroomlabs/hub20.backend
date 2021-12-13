from django.db import models

from hub20.apps.blockchain.validators import uri_parsable_scheme_validator


class TokenLogoURLField(models.URLField):
    default_validators = [uri_parsable_scheme_validator(("https", "http", "ipfs", "ens"))]
