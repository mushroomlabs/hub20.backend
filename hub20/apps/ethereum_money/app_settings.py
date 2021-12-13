from django.conf import settings

TRANSFER_GAS_LIMIT = getattr(settings, "ETHEREUM_MONEY_TRANSFER_GAS_LIMIT", 200_000)
HD_WALLET_ROOT_KEY = getattr(settings, "ETHEREUM_HD_WALLET_ROOT_KEY", None)
HD_WALLET_MNEMONIC = getattr(settings, "ETHEREUM_HD_WALLET_MNEMONIC", None)
