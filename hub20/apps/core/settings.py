import logging

from django.conf import settings
from django.test.signals import setting_changed

logger = logging.getLogger(__name__)


class AppSettings:
    class Checkout:
        lifetime = 15 * 60  # In seconds

    class Blockchain:
        minimum_confirmations = 10
        payment_route_lifetime = 100  # In blocks
        scan_range = 5000

    class Raiden:
        payment_route_lifetime = 15 * 60  # In seconds

    class HDWallet:
        root_key = None
        mnemonic = None

    def __init__(self):
        self.load()

    def load(self):
        ATTRS = {
            "BLOCKCHAIN_MININUM_CONFIRMATIONS": (self.Blockchain, "minimum_confirmations"),
            "BLOCKCHAIN_ROUTE_LIFETIME": (self.Blockchain, "payment_route_lifetime"),
            "BLOCKCHAIN_SCAN_BLOCK_RANGE": (self.Blockchain, "scan_range"),
            "ETHEREUM_HD_WALLET_MNEMONIC": (self.HDWallet, "mnemonic"),
            "ETHEREUM_HD_WALLET_ROOT_KEY": (self.HDWallet, "root_key"),
        }
        user_settings = getattr(settings, "HUB20", {})

        for setting, value in user_settings.items():
            if setting not in ATTRS:
                logger.warning(f"Ignoring {setting} as it is not a setting for HUB20")
                continue

            setting_class, attr = ATTRS[setting]
            setattr(setting_class, attr, value)


app_settings = AppSettings()


def reload_settings(*args, **kw):
    global app_settings
    setting = kw["setting"]
    if setting == "HUB20":
        app_settings.load()


setting_changed.connect(reload_settings)
