from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from hub20.apps.core.api import consumer_patterns
from hub20.apps.core.middleware import TokenAuthMiddlewareStack

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": TokenAuthMiddlewareStack(URLRouter(consumer_patterns)),
    }
)

__all__ = ["application"]
