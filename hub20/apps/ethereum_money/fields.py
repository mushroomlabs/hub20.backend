from django.db import models

from .validators import token_logo_uri_validator


class TokenLogoURLField(models.URLField):
    default_validators = [token_logo_uri_validator]
