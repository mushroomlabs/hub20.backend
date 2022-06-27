from enum import Enum


class Events(Enum):
    CHANNEL_OPENED = "raiden.channel.opened"
    CHANNEL_CLOSED = "raiden.channel.closed"
