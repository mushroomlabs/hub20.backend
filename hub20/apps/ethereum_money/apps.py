from django.apps import AppConfig


class EthereumMoneyConfig(AppConfig):
    name = "hub20.apps.ethereum_money"
    verbose_name = "Token Management"

    def ready(self):
        from . import signals  # noqa
        from . import tasks  # noqa
