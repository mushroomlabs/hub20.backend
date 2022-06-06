from __future__ import annotations

import datetime
from typing import Optional

from django.db import models
from django.db.models import ExpressionWrapper, F
from django.utils import timezone

from hub20.apps.core.exceptions import RoutingError
from hub20.apps.core.models.payments import (
    Payment as BasePayment,
    PaymentRoute,
    PaymentRouteQuerySet,
)
from hub20.apps.core.settings import app_settings
from hub20.apps.ethereum.models import Erc20Token

from .networks import RaidenPaymentNetwork
from .raiden import Channel, Payment, Raiden


def calculate_raiden_payment_window():
    return datetime.timedelta(seconds=app_settings.Raiden.payment_route_lifetime)


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
        return self.filter(
            payments__raidenpayment__isnull=False,
            payments__raidenpayment__identifier=F("deposit__identifier"),
        )

    def open(self) -> models.QuerySet:
        return self.available()


class RaidenPaymentRoute(PaymentRoute):
    NETWORK = RaidenPaymentNetwork

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
            payment_network = channel.raiden.chain.raidenpaymentnetwork
            return cls.objects.create(
                raiden=channel.raiden,
                deposit=deposit,
                network=payment_network,
            )
        else:
            raise RoutingError(
                f"No raiden node available to accept {deposit.currency.symbol} payments"
            )


class RaidenPayment(BasePayment):
    payment = models.OneToOneField(Payment, unique=True, on_delete=models.CASCADE)

    @property
    def identifier(self):
        return f"{self.payment.identifier}-{self.id}"


__all__ = ["RaidenPayment", "RaidenPaymentRoute"]
