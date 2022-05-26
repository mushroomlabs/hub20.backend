from django.conf import settings

WEB3_TRANSFER_GAS_LIMIT = int(getattr(settings, "WEB3_TRANSFER_GAS_LIMIT", 0) or 200_000)
WEB3_REQUEST_TIMEOUT = int(getattr(settings, "WEB3_REQUEST_TIMEOUT", 0) or 10)
