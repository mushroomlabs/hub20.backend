import factory
from factory import fuzzy

from hub20.apps.core.factories.payments import PaymentOrderFactory, PaymentRouteFactory
from hub20.apps.core.models.payments import PaymentConfirmation

from ..models import BlockchainPayment, BlockchainPaymentRoute
from .blockchain import TransactionFactory
from .networks import BlockchainPaymentNetworkFactory
from .tokens import Erc20TokenFactory, EtherFactory
from .wallets import BaseWalletFactory


class EtherPaymentOrderFactory(PaymentOrderFactory):
    currency = factory.SubFactory(EtherFactory)


class Erc20TokenPaymentOrderFactory(PaymentOrderFactory):
    currency = factory.SubFactory(Erc20TokenFactory)


class EtherBlockchainPaymentRouteFactory(PaymentRouteFactory):
    deposit = factory.SubFactory(EtherPaymentOrderFactory)
    network = factory.SubFactory(
        BlockchainPaymentNetworkFactory, chain=factory.SelfAttribute("..deposit.currency.chain")
    )
    account = factory.SubFactory(BaseWalletFactory)
    payment_window = factory.LazyAttribute(
        lambda obj: (
            obj.deposit.currency.chain.highest_block,
            obj.deposit.currency.chain.highest_block + 100,
        )
    )

    class Meta:
        model = BlockchainPaymentRoute
        django_get_or_create = ("account",)


class Erc20TokenBlockchainPaymentRouteFactory(EtherBlockchainPaymentRouteFactory):
    deposit = factory.SubFactory(Erc20TokenPaymentOrderFactory)


class EtherBlockchainPaymentFactory(factory.django.DjangoModelFactory):
    route = factory.SubFactory(EtherBlockchainPaymentRouteFactory)
    transaction = factory.SubFactory(TransactionFactory)
    currency = factory.SelfAttribute("route.deposit.currency")
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)

    class Meta:
        model = BlockchainPayment


class Erc20TokenBlockchainPaymentFactory(EtherBlockchainPaymentFactory):
    route = factory.SubFactory(Erc20TokenBlockchainPaymentRouteFactory)


class EtherPaymentConfirmationFactory(factory.django.DjangoModelFactory):
    payment = factory.SubFactory(EtherBlockchainPaymentFactory)

    class Meta:
        model = PaymentConfirmation


class Erc20TokenPaymentConfirmationFactory(EtherPaymentConfirmationFactory):
    payment = factory.SubFactory(Erc20TokenBlockchainPaymentFactory)


__all__ = [
    "Erc20TokenPaymentOrderFactory",
    "Erc20TokenBlockchainPaymentRouteFactory",
    "Erc20TokenBlockchainPaymentFactory",
    "Erc20TokenPaymentConfirmationFactory",
    "EtherPaymentOrderFactory",
    "EtherBlockchainPaymentRouteFactory",
    "EtherBlockchainPaymentFactory",
    "EtherPaymentConfirmationFactory",
]
