import factory

from hub20.apps.core.factories.checkout import CheckoutFactory

from .payments import Erc20TokenPaymentOrderFactory


class Erc20TokenCheckoutFactory(CheckoutFactory):
    order = factory.SubFactory(
        Erc20TokenPaymentOrderFactory,
        user=factory.SelfAttribute("..store.owner"),
        reference=factory.fuzzy.FuzzyText(length=30, prefix="checkout-"),
    )


__all__ = ["Erc20TokenCheckoutFactory"]
