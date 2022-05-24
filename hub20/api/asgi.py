from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from django.urls import path

from hub20.apps.core.api import consumer_patterns

from .middleware import TokenAuthMiddlewareStack

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": TokenAuthMiddlewareStack(
            URLRouter(
                [
                    path("ws/", URLRouter(consumer_patterns)),
                ]
            )
        ),
    }
)
