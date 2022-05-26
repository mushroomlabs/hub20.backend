from hub20.apps.core.apps import Hub20PaymentNetworkConfig


class EthereumConfig(Hub20PaymentNetworkConfig):
    name = "hub20.apps.ethereum"
    verbose_name = "Ethereum Blockchains"

    network_name = "ethereum"
    description = "Ethereum and Ethereum-compatible blockchains"

    def ready(self):
        from . import signals  # noqa
        from . import tasks  # noqa
