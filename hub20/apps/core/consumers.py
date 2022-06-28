import logging
import uuid
from typing import Union

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from . import models

logger = logging.getLogger(__name__)


def accept_subprotocol(consumer):
    try:
        subprotocol = consumer.scope["subprotocols"][0]
        consumer.accept(subprotocol)
    except IndexError:
        consumer.accept()


class PaymentNetworkEventsConsumer(JsonWebsocketConsumer):
    GROUP_NAME = "network.events"

    def connect(self):
        accept_subprotocol(self)
        async_to_sync(self.channel_layer.group_add)(self.GROUP_NAME, self.channel_name)

    def notify_event(self, message):
        message.pop("type", None)
        event = message.pop("event", "notification")
        self.send_json({"event": event, "data": message})

    def disconnect(self, code):
        async_to_sync(self.channel_layer.group_discard)(self.GROUP_NAME, self.channel_name)
        return super().disconnect(code)


class CheckoutConsumer(JsonWebsocketConsumer):
    @classmethod
    def get_group_name(cls, checkout_id: Union[uuid.UUID, str]) -> str:
        uid = uuid.UUID(str(checkout_id))
        return f"checkout.{uid.hex}"

    def connect(self):
        checkout_id = self.scope["url_route"]["kwargs"].get("pk")

        if not models.Checkout.objects.filter(id=checkout_id).first():
            self.close()

        group_name = self.__class__.get_group_name(checkout_id)
        async_to_sync(self.channel_layer.group_add)(group_name, self.channel_name)

        accept_subprotocol(self)
        logger.info(f"Checkout consumer {group_name} connected")

    def checkout_event(self, message):
        logger.info(f"Message received: {message}")
        message.pop("type", None)
        message["event"] = message.pop("event_name", None)

        logger.debug(f"Sending {message['event']} notification on {self.channel_name}...")
        self.send_json(message)
