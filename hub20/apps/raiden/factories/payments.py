import factory
from factory import fuzzy

from hub20.apps.core.factories import PaymentOrderFactory, PaymentRouteFactory
from hub20.apps.core.models.payments import PaymentConfirmation
from hub20.apps.ethereum.factories import Erc20TokenFactory

from ..models import RaidenPayment, RaidenPaymentRoute
from .networks import RaidenPaymentNetworkFactory
from .raiden import PaymentEventFactory, RaidenFactory


class RaidenPaymentOrderFactory(PaymentOrderFactory):
    currency = factory.SubFactory(Erc20TokenFactory)


class RaidenPaymentRouteFactory(PaymentRouteFactory):
    deposit = factory.SubFactory(RaidenPaymentOrderFactory)
    network = factory.SubFactory(
        RaidenPaymentNetworkFactory, chain=factory.SelfAttribute("..deposit.currency.chain")
    )
    raiden = factory.SubFactory(RaidenFactory)

    class Meta:
        model = RaidenPaymentRoute
        django_get_or_create = ("raiden",)


class RaidenPaymentFactory(factory.django.DjangoModelFactory):
    route = factory.SubFactory(RaidenPaymentRouteFactory)
    payment = factory.SubFactory(
        PaymentEventFactory,
        amount=factory.SelfAttribute("..amount"),
        channel__token_network__token=factory.SelfAttribute("....route.deposit.currency"),
    )
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SelfAttribute(".route.deposit.currency")

    class Meta:
        model = RaidenPayment

    class Params:
        token = factory.SubFactory(Erc20TokenFactory)


class RaidenPaymentConfirmationFactory(factory.django.DjangoModelFactory):
    payment = factory.SubFactory(RaidenPaymentFactory)

    class Meta:
        model = PaymentConfirmation


__all__ = [
    "RaidenPaymentOrderFactory",
    "RaidenPaymentRouteFactory",
    "RaidenPaymentFactory",
    "RaidenPaymentConfirmationFactory",
]
