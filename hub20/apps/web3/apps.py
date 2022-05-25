from django.apps import AppConfig


class Web3Config(AppConfig):
    name = "hub20.apps.web3"
    verbose_name = "Web3 - Base Layer"

    def ready(self):
        from . import signals  # noqa
        from . import tasks  # noqa
