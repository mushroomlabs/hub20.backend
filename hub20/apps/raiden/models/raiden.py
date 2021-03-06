from __future__ import annotations

import datetime
from typing import Optional
from urllib.parse import urlparse

from django.db import models
from django.db.models import F
from model_utils.choices import Choices
from model_utils.managers import QueryManager
from model_utils.models import StatusModel

from hub20.apps.core.models.networks import PaymentNetwork_T
from hub20.apps.core.models.tokens import TokenAmount, TokenAmountField
from hub20.apps.core.settings import app_settings
from hub20.apps.core.validators import uri_parsable_scheme_validator
from hub20.apps.ethereum.models import Chain, Erc20Token, EthereumAddressField, Uint256Field

CHANNEL_STATUSES = Choices(
    "opened", "waiting_for_settle", "settling", "settled", "unusable", "closed", "closing"
)
raiden_url_validator = uri_parsable_scheme_validator(("http", "https"))


def calculate_raiden_payment_window():
    return datetime.timedelta(seconds=app_settings.Raiden.payment_route_lifetime)


class RaidenURLField(models.URLField):
    default_validators = [raiden_url_validator]


class TokenNetwork(models.Model):
    address = EthereumAddressField()
    token = models.OneToOneField(Erc20Token, on_delete=models.CASCADE)

    @property
    def chain(self):
        return self.token.chain

    def __str__(self):
        return f"{self.address} - ({self.token.symbol} @ {self.token.chain_id})"


class Raiden(models.Model):
    url = RaidenURLField(unique=True)
    address = EthereumAddressField()
    chain = models.OneToOneField(Chain, related_name="raiden_node", on_delete=models.PROTECT)

    @property
    def hostname(self):
        return urlparse(self.url).hostname

    @property
    def payment_network(self) -> PaymentNetwork_T:
        return self.chain.raidenpaymentnetwork

    @property
    def token_networks(self):
        return TokenNetwork.objects.filter(
            channel__status=Channel.STATUS.opened, channel__raiden=self
        )

    @property
    def open_channels(self):
        return self.channels.filter(status=Channel.STATUS.opened)

    @property
    def payments(self):
        return Payment.objects.filter(channel__raiden=self)

    @property
    def payments_received(self):
        return Payment.received.filter(channel__raiden=self)

    @property
    def payments_sent(self):
        return Payment.sent.filter(channel__raiden=self)

    def __str__(self):
        return f"{self.hostname} ({self.chain.short_name}:{self.address})"


class Channel(StatusModel):
    STATUS = CHANNEL_STATUSES
    raiden = models.ForeignKey(Raiden, on_delete=models.CASCADE, related_name="channels")
    token_network = models.ForeignKey(TokenNetwork, on_delete=models.CASCADE)
    identifier = models.PositiveIntegerField()
    partner_address = EthereumAddressField(db_index=True)
    balance = TokenAmountField()
    total_deposit = TokenAmountField()
    total_withdraw = TokenAmountField()

    objects = models.Manager()
    funded = QueryManager(status=STATUS.opened, balance__gt=0)
    available = QueryManager(status=STATUS.opened)

    @property
    def token(self):
        return self.token_network.token

    @property
    def balance_amount(self) -> TokenAmount:
        return TokenAmount(amount=self.balance, currency=self.token)

    @property
    def deposit_amount(self) -> TokenAmount:
        return TokenAmount(amount=self.total_deposit, currency=self.token)

    @property
    def withdraw_amount(self) -> TokenAmount:
        return TokenAmount(amount=self.total_withdraw, currency=self.token)

    @property
    def last_event_timestamp(self) -> Optional[datetime.datetime]:
        latest_event = self.payments.order_by("-timestamp").first()
        return latest_event and latest_event.timestamp

    def __str__(self):
        return f"Channel {self.identifier} ({self.partner_address})"

    @classmethod
    def make(cls, raiden: Raiden, **channel_data) -> Optional[Channel]:
        token_network_address = channel_data.pop("token_network_address")
        token_address = channel_data.pop("token_address")

        token = Erc20Token.objects.filter(address=token_address).first()

        assert token is not None
        assert token.chain == raiden.chain

        token_network, _ = TokenNetwork.objects.get_or_create(
            address=token_network_address, token=token
        )

        assert token_network.token.address == token_address

        balance = token.from_wei(channel_data.pop("balance"))
        total_deposit = token.from_wei(channel_data.pop("total_deposit"))
        total_withdraw = token.from_wei(channel_data.pop("total_withdraw"))

        channel, _ = raiden.channels.update_or_create(
            identifier=channel_data["channel_identifier"],
            partner_address=channel_data["partner_address"],
            token_network=token_network,
            defaults={
                "status": channel_data["state"],
                "balance": balance.amount,
                "total_deposit": total_deposit.amount,
                "total_withdraw": total_withdraw.amount,
            },
        )
        return channel

    class Meta:
        unique_together = (("raiden", "token_network", "identifier"),)


class Payment(models.Model):
    MAX_IDENTIFIER_ID = (2**64) - 1
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="payments")
    amount = TokenAmountField()
    timestamp = models.DateTimeField()
    identifier = Uint256Field()
    sender_address = EthereumAddressField()
    receiver_address = EthereumAddressField()
    objects = models.Manager()
    sent = QueryManager(sender_address=F("channel__raiden__address"))
    received = QueryManager(receiver_address=F("channel__raiden__address"))

    @property
    def token(self):
        return self.channel.token

    @property
    def as_token_amount(self) -> TokenAmount:
        return TokenAmount(amount=self.amount, currency=self.token)

    @property
    def partner_address(self):
        return self.receiver_address if self.is_outgoing else self.sender_address

    @property
    def is_outgoing(self):
        return self.channel.raiden.address == self.sender_address

    @property
    def is_incoming(self):
        return self.channel.raiden.address == self.receiver_address

    @classmethod
    def make(cls, channel: Channel, **payment_data):
        sender_address = payment_data.pop("sender_address")
        receiver_address = payment_data.pop("receiver_address")
        identifier = payment_data.pop("identifier")

        payment, _ = channel.payments.update_or_create(
            channel=channel,
            sender_address=sender_address,
            receiver_address=receiver_address,
            identifier=identifier,
            defaults=payment_data,
        )
        return payment

    class Meta:
        unique_together = ("channel", "identifier", "sender_address", "receiver_address")


__all__ = ["TokenNetwork", "Raiden", "Channel", "Payment", "RaidenURLField"]
