from django.apps import AppConfig


class BlockchainConfig(AppConfig):
    name = "hub20.apps.blockchain"
    verbose_name = "Web3 - Base Layer"

    def ready(self):
        from . import signals  # noqa
        from . import tasks  # noqa
