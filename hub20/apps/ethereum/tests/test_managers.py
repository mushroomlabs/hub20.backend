from django.test import TestCase

from hub20.apps.core.factories.networks import InternalPaymentNetworkFactory
from hub20.apps.core.models.payments import PaymentConfirmation

from ..factories import (
    Erc20TokenBlockchainPaymentFactory,
    Erc20TokenBlockchainPaymentRouteFactory,
    Erc20TokenFactory,
)
from ..models import BlockchainPaymentRoute, Erc20Token


class PaymentOrderManagerTestCase(TestCase):
    def setUp(self):
        InternalPaymentNetworkFactory()
        self.route = Erc20TokenBlockchainPaymentRouteFactory()
        self.order = self.route.deposit

    def test_order_with_partial_payment_is_open(self):
        partial_payment_amount = self.order.as_token_amount * 0.5
        payment = Erc20TokenBlockchainPaymentFactory(
            route=self.route, payment_amount=partial_payment_amount
        )

        PaymentConfirmation.objects.create(payment=payment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_unconfirmed_payment_is_open(self):
        Erc20TokenBlockchainPaymentFactory(
            route=self.route, payment_amount=self.order.as_token_amount
        )
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_multiple_payments_is_not_open(self):
        partial_payment_amount = self.order.as_token_amount * 0.5
        first_payment = Erc20TokenBlockchainPaymentFactory(
            route=self.route, payment_amount=partial_payment_amount
        )
        PaymentConfirmation.objects.create(payment=first_payment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

        second_payment = Erc20TokenBlockchainPaymentFactory(
            route=self.route, payment_amount=partial_payment_amount
        )
        PaymentConfirmation.objects.create(payment=second_payment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_confirmed_payment_is_not_open(self):
        payment = Erc20TokenBlockchainPaymentFactory(
            route=self.route, payment_amount=self.order.as_token_amount
        )
        PaymentConfirmation.objects.create(payment=payment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())


class TokenManagerTestCase(TestCase):
    def setUp(self):
        self.listed_token = Erc20TokenFactory()
        self.unlisted_token = Erc20TokenFactory(is_listed=False)

    def test_tradeable_manager_works_on_derived_classes(self):
        self.assertEqual(Erc20Token.tradeable.count(), 1)
        self.assertEqual(Erc20Token.tradeable.select_subclasses().count(), 1)


__all__ = ["PaymentOrderManagerTestCase", "TokenManagerTestCase"]
