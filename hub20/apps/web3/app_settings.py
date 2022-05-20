from django.conf import settings

BLOCK_SCAN_RANGE = int(getattr(settings, "BLOCKCHAIN_SCAN_BLOCK_RANGE", 0) or 5000)
FETCH_BLOCK_TASK_PRIORITY = int(getattr(settings, "BLOCKCHAIN_FETCH_BLOCK_PRIORITY", 0) or 9)
WEB3_TRANSFER_GAS_LIMIT = int(getattr(settings, "WEB3_TRANSFER_GAS_LIMIT", 0) or 200_000)
WEB3_REQUEST_TIMEOUT = int(getattr(settings, "WEB3_REQUEST_TIMEOUT", 0) or 10)
PAYMENT_ROUTE_LIFETIME = 100  # In blocks
