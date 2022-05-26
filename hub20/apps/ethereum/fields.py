from django.db import models

from . import validators


class Web3ProviderURLField(models.URLField):
    default_validators = [validators.web3_url_validator]
