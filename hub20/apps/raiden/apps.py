from django.apps import AppConfig

from hub20.apps.core.apps import Hub20PaymentNetworkConfig


class RaidenConfig(AppConfig, Hub20PaymentNetworkConfig):
    name = "hub20.apps.raiden"

    network_name = "raiden"
    description = "Layer-2 solution for ethereum networks, enables off-chain ERC20 token transfers"

    def ready(self):
        from . import handlers  # noqa
        from . import serializers  # noqa
        from . import signals  # noqa
