from django.conf import settings

HD_WALLET_ROOT_KEY = getattr(settings, "ETHEREUM_HD_WALLET_ROOT_KEY", None)
HD_WALLET_MNEMONIC = getattr(settings, "ETHEREUM_HD_WALLET_MNEMONIC", None)
