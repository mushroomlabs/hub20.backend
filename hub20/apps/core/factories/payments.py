import factory
from factory import fuzzy

from ..models import InternalPaymentRoute, Payment, PaymentConfirmation, PaymentOrder, PaymentRoute
from .tokens import BaseTokenFactory
from .users import UserFactory


class PaymentOrderFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory(UserFactory)
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    reference = factory.fuzzy.FuzzyText(length=30, prefix="order-")
    currency = factory.SubFactory(BaseTokenFactory)

    class Meta:
        model = PaymentOrder


class PaymentRouteFactory(factory.django.DjangoModelFactory):
    deposit = factory.SubFactory(PaymentOrderFactory)

    class Meta:
        model = PaymentRoute


class InternalPaymentRouteFactory(PaymentRouteFactory):
    class Meta:
        model = InternalPaymentRoute


class PaymentFactory(factory.django.DjangoModelFactory):
    route = factory.SubFactory(PaymentRouteFactory)
    currency = factory.SelfAttribute(".route.deposit.currency")
    amount = factory.SelfAttribute(".route.deposit.amount")

    class Meta:
        model = Payment


class PaymentConfirmationFactory(factory.django.DjangoModelFactory):
    payment = factory.SubFactory(PaymentFactory)

    class Meta:
        model = PaymentConfirmation


__all__ = [
    "PaymentOrderFactory",
    "PaymentRouteFactory",
    "PaymentFactory",
    "PaymentConfirmationFactory",
    "InternalPaymentRouteFactory",
]
