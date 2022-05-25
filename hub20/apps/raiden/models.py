from __future__ import annotations

import datetime
from typing import Optional
from urllib.parse import urlparse

from django.contrib.postgres.fields import HStoreField
from django.db import models
from django.db.models import ExpressionWrapper, F
from django.utils import timezone
from model_utils.choices import Choices
from model_utils.managers import QueryManager
from model_utils.models import StatusModel

from hub20.apps.core.exceptions import RoutingError, TransferError
from hub20.apps.core.fields import EthereumAddressField, Uint256Field
from hub20.apps.core.models.payments import (
    Payment as BasePayment,
    PaymentRoute,
    PaymentRouteQuerySet,
)
from hub20.apps.core.models.tokens import TokenAmount, TokenAmountField
from hub20.apps.core.models.transfers import TransferConfirmation, TransferReceipt, Withdrawal
from hub20.apps.core.settings import app_settings
from hub20.apps.core.validators import uri_parsable_scheme_validator
from hub20.apps.web3.models import Chain, Erc20Token

from .exceptions import RaidenPaymentError

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
        return f"Raiden @ {self.url} (Chain #{self.chain_id})"


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


# Payments
class RaidenRouteQuerySet(PaymentRouteQuerySet):
    def with_expiration(self) -> models.QuerySet:
        return self.annotate(
            expires_on=ExpressionWrapper(
                F("created") + F("payment_window"), output_field=models.DateTimeField()
            )
        )

    def expired(self, at: Optional[datetime.datetime] = None) -> models.QuerySet:
        date_value = at or timezone.now()
        return self.with_expiration().filter(expires_on__lt=date_value)

    def available(self, at: Optional[datetime.datetime] = None) -> models.QuerySet:
        date_value = at or timezone.now()
        return (
            self.with_expiration()
            .filter(payments__raidenpayment__isnull=True)
            .filter(created__lte=date_value, expires_on__gte=date_value)
        )

    def used(self) -> models.QuerySet:
        return self.filter(payments__raidenpayment__isnull=False)


class RaidenPaymentRoute(PaymentRoute):
    NETWORK = "raiden"

    payment_window = models.DurationField(default=calculate_raiden_payment_window)
    raiden = models.ForeignKey(Raiden, on_delete=models.CASCADE, related_name="payment_routes")

    objects = RaidenRouteQuerySet.as_manager()

    @property
    def is_expired(self):
        return self.expiration_time < timezone.now()

    @property
    def expiration_time(self):
        return self.created + self.payment_window

    @staticmethod
    def calculate_payment_window():
        return calculate_raiden_payment_window()

    @classmethod
    def is_usable_for_token(cls, token: Erc20Token):
        return token.is_listed and hasattr(token, "tokennetwork")

    @classmethod
    def make(cls, deposit):
        channels = Channel.available.filter(token_network__token=deposit.currency)

        if channels.exists():
            channel = channels.order_by("?").first()
            return cls.objects.create(raiden=channel.raiden, deposit=deposit)
        else:
            raise RoutingError(
                f"No raiden node available to accept {deposit.currency.symbol} payments"
            )


class RaidenPayment(BasePayment):
    payment = models.OneToOneField(Payment, unique=True, on_delete=models.CASCADE)

    @property
    def identifier(self):
        return f"{self.payment.identifier}-{self.id}"


# Transfers
class RaidenWithdrawalReceipt(TransferReceipt):
    payment_data = HStoreField()


class RaidenWithdrawalConfirmation(TransferConfirmation):
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE)


class RaidenWithdrawal(Withdrawal):
    address = EthereumAddressField(db_index=True)

    def _execute(self):
        try:
            raiden_client = RaidenClient.select_for_transfer(
                amount=self.amount, address=self.address
            )
            payment_data = raiden_client.transfer(
                amount=self.as_token_amount,
                address=self.address,
                identifier=raiden_client._ensure_valid_identifier(self.identifier),
            )
            RaidenWithdrawalReceipt.objects.create(transfer=self, payment_data=payment_data)
        except AssertionError:
            raise TransferError("Incorrect transfer method")
        except RaidenPaymentError as exc:
            raise TransferError(exc.message) from exc

    class Meta:
        proxy = True


__all__ = [
    "TokenNetwork",
    "Raiden",
    "Channel",
    "Payment",
    "RaidenWithdrawal",
    "RaidenWithdrawalReceipt",
    "RaidenWithdrawalConfirmation",
]
