from django.apps import AppConfig

from hub20.apps.core.apps import Hub20PaymentNetworkConfig


class EthereumConfig(AppConfig, Hub20PaymentNetworkConfig):
    name = "hub20.apps.ethereum"
    verbose_name = "Ethereum Blockchains"

    network_name = "ethereum"
    description = "Ethereum and Ethereum-compatible blockchains"

    def ready(self):
        from . import handlers  # noqa
        from . import signals  # noqa
        from . import tasks  # noqa
