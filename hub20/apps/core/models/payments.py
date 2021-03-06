import datetime
import logging
import random
from typing import Optional, TypeVar, Union

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from model_utils.managers import InheritanceManager
from model_utils.models import TimeStampedModel

from ..choices import DEPOSIT_STATUS
from ..exceptions import RoutingError
from .base import BaseModel, PolymorphicModelMixin
from .networks import InternalPaymentNetwork, PaymentNetwork
from .providers import PaymentNetworkProvider_T
from .tokens import BaseToken, TokenAmountField, TokenValueModel

logger = logging.getLogger(__name__)


def generate_payment_route_id():
    # Default payment identifier generated by Raiden's web UI is based on unix
    # time. We would like to make the distinction between payment ids
    # generated by default and those generated by us.

    LOWER_BOUND = 2**48  # Enough to take us to the year 10889.
    UPPER_BOUND = 2**53 - 1  # Javascript can not handle numbers bigger than 2^53 - 1

    return random.randint(LOWER_BOUND, UPPER_BOUND)


class PaymentOrderQuerySet(models.QuerySet):
    def unpaid(self):
        q_no_payment = Q(total_paid__isnull=True)
        q_low_payment = Q(total_paid__lt=F("amount"))

        return self.annotate(total_paid=Sum("routes__payments__amount")).filter(
            q_no_payment | q_low_payment
        )

    def paid(self):
        return self.annotate(total_paid=Sum("routes__payments__amount")).filter(
            total_paid__gte=F("amount")
        )


class PaymentRouteQuerySet(models.QuerySet):
    def with_payment_amounts(self) -> models.QuerySet:
        return self.annotate(
            currency=F("payments__currency"),
            total_paid=Coalesce(
                Sum("payments__amount"), Value(0), output_field=TokenAmountField()
            ),
            total_confirmed=Coalesce(
                Sum("payments__amount", filter=Q(payments__confirmation__isnull=False)),
                Value(0),
                output_field=TokenAmountField(),
            ),
        )

    def used(self) -> models.QuerySet:
        return self.with_payment_amounts().filter(
            total_paid__gte=F("deposit__amount"), currency=F("deposit__currency")
        )


class InternalPaymentRouteQuerySet(PaymentRouteQuerySet):
    def available(self, at: Optional[datetime.datetime] = None) -> models.QuerySet:
        date_value = at or timezone.now()
        return self.filter(created__lte=date_value)

    def open(self) -> models.QuerySet:
        return self.filter(payments__internalpayment__isnull=True)


class Deposit(BaseModel, TimeStampedModel):
    STATUS = DEPOSIT_STATUS

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_key = models.SlugField(null=True)
    currency = models.ForeignKey(BaseToken, on_delete=models.PROTECT)

    @property
    def payments(self):
        return Payment.objects.filter(route__deposit=self).select_subclasses()

    @property
    def confirmed_payments(self):
        return self.payments.filter(confirmation__isnull=False)

    @property
    def total_transferred(self):
        return self.payments.aggregate(total=Sum("amount")).get("total") or 0

    @property
    def total_confirmed(self):
        return self.confirmed_payments.aggregate(total=Sum("amount")).get("total") or 0

    @property
    def is_expired(self):
        routes = self.routes.select_subclasses()
        return routes.count() > 0 and all([route.is_expired for route in routes])

    @property
    def status(self):
        return self.STATUS.expired if self.is_expired else self.STATUS.open


class PaymentOrder(Deposit, TokenValueModel):
    reference = models.CharField(max_length=200, null=True, blank=True)
    objects = PaymentOrderQuerySet.as_manager()

    @property
    def due_amount(self):
        return max(0, self.amount - self.total_transferred)

    @property
    def is_paid(self):
        return self.due_amount <= 0

    @property
    def is_confirmed(self):
        return self.is_paid and self.total_confirmed >= self.amount

    @property
    def status(self):
        if self.is_confirmed:
            return self.STATUS.confirmed
        elif self.is_paid:
            return self.STATUS.paid
        else:
            return self.STATUS.open


class PaymentRoute(BaseModel, TimeStampedModel, PolymorphicModelMixin):
    deposit = models.ForeignKey(Deposit, on_delete=models.CASCADE, related_name="routes")
    network = models.ForeignKey(PaymentNetwork, on_delete=models.CASCADE, related_name="routes")
    identifier = models.BigIntegerField(default=generate_payment_route_id, unique=True)
    objects = InheritanceManager()

    @property
    def is_expired(self):
        return False

    @property
    def is_used(self):
        return self.payments.exists()

    @property
    def is_open(self):
        return not self.is_expired

    @property
    def provider(self) -> Union[PaymentNetworkProvider_T, None]:
        return self.network.providers(manager="available").select_subclasses().first()

    def process(self):
        raise NotImplementedError("This method should be implemented by derived classes")

    @staticmethod
    def find_route_model(network):
        network_type = type(network)
        try:
            return [rt for rt in PaymentRoute.__subclasses__() if rt.NETWORK == network_type].pop()
        except IndexError:
            raise RoutingError(f"Could not find route model for {network.type} payment network")

    @classmethod
    def make(cls, deposit):
        raise NotImplementedError


class InternalPaymentRoute(PaymentRoute):
    NETWORK = InternalPaymentNetwork
    objects = InternalPaymentRouteQuerySet.as_manager()

    def process(self):
        """
        There is not anything to be done here, yet.
        """
        pass


class Payment(BaseModel, TimeStampedModel, TokenValueModel, PolymorphicModelMixin):
    route = models.ForeignKey(PaymentRoute, on_delete=models.PROTECT, related_name="payments")
    objects = InheritanceManager()

    @property
    def is_confirmed(self):
        return hasattr(self, "confirmation")


class InternalPayment(Payment):
    memo = models.TextField(null=True, blank=True)

    @property
    def identifier(self):
        return str(self.id)


class PaymentConfirmation(BaseModel, TimeStampedModel):
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name="confirmation")


PaymentRoute_T = TypeVar("PaymentRoute_T", bound=PaymentRoute)
Payment_T = TypeVar("Payment_T", bound=Payment)


__all__ = [
    "Deposit",
    "PaymentOrder",
    "PaymentRoute",
    "PaymentRouteQuerySet",
    "InternalPaymentRoute",
    "Payment",
    "InternalPayment",
    "PaymentConfirmation",
    "Payment_T",
    "PaymentRoute_T",
]
