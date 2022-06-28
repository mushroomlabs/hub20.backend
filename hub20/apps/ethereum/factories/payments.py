import factory

from hub20.apps.core.factories.payments import PaymentOrderFactory, PaymentRouteFactory
from hub20.apps.core.models.payments import PaymentConfirmation

from ..models import BlockchainPayment, BlockchainPaymentRoute
from .networks import BlockchainPaymentNetworkFactory
from .tokens import (
    Erc20TokenAmountFactory,
    Erc20TokenFactory,
    Erc20TokenTransactionFactory,
    EtherAmountFactory,
    EtherFactory,
    EtherTransactionFactory,
)
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
    transaction = factory.SubFactory(
        EtherTransactionFactory,
        recipient=factory.SelfAttribute("..route.account.address"),
        amount=factory.SelfAttribute("..payment_amount"),
    )
    currency = factory.LazyAttribute(lambda obj: obj.payment_amount.currency)
    amount = factory.LazyAttribute(lambda obj: obj.payment_amount.amount)

    class Meta:
        model = BlockchainPayment

    class Params:
        payment_amount = factory.SubFactory(EtherAmountFactory)


class Erc20TokenBlockchainPaymentFactory(EtherBlockchainPaymentFactory):
    route = factory.SubFactory(Erc20TokenBlockchainPaymentRouteFactory)
    transaction = factory.SubFactory(
        Erc20TokenTransactionFactory,
        recipient=factory.SelfAttribute("..route.account.address"),
        amount=factory.SelfAttribute("..payment_amount"),
    )

    class Params:
        payment_amount = factory.SubFactory(Erc20TokenAmountFactory)


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
