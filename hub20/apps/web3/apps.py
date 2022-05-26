from hub20.apps.core.apps import Hub20PaymentNetworkConfig


class Web3Config(Hub20PaymentNetworkConfig):
    name = "hub20.apps.web3"
    verbose_name = "Web3 - Base Layer"

    network_name = "ethereum"
    description = "Ethereum and Ethereum-compatible blockchains"

    def ready(self):
        from . import signals  # noqa
        from . import tasks  # noqa
