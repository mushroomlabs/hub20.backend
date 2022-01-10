from django.apps import AppConfig


class WalletConfig(AppConfig):
    name = "hub20.apps.wallet"


default_app_config = "hub20.apps.wallet.apps.WalletConfig"
