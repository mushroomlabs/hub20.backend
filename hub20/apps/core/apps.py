from django.apps import AppConfig


class Hub20PaymentNetworkConfig(AppConfig):
    network_name = None
    description = None


class Hub20Config(Hub20PaymentNetworkConfig):
    name = "hub20.apps.core"
    network_name = "internal"

    def ready(self):
        from . import handlers  # noqa
        from . import signals  # noqa
