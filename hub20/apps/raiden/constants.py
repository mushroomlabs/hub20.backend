from enum import Enum


class Events(Enum):
    CHANNEL_OPENED = "raiden.channel.opened"
    CHANNEL_CLOSED = "raiden.channel.closed"
    DEPOSIT_CONFIRMED = "raiden.deposit.confirmed"
    ROUTE_EXPIRED = "raiden.route.expired"
    PROVIDER_OFFLINE = "raiden.provider.offline"
    PROVIDER_ONLINE = "raiden.provider.online"
