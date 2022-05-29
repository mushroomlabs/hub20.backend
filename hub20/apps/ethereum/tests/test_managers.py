from django.test import TestCase

from hub20.apps.core.factories.networks import InternalPaymentNetworkFactory
from hub20.apps.core.models.payments import PaymentConfirmation

from ..factories import Erc20TokenBlockchainPaymentRouteFactory
from ..models import BlockchainPaymentRoute
from .utils import add_token_to_account


class PaymentOrderManagerTestCase(TestCase):
    def setUp(self):
        InternalPaymentNetworkFactory()
        self.route = Erc20TokenBlockchainPaymentRouteFactory()
        self.order = self.route.deposit

    def test_order_with_partial_payment_is_open(self):
        partial_payment_amount = self.order.as_token_amount * 0.5
        tx = add_token_to_account(self.route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=tx.blockchainpayment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_unconfirmed_payment_is_open(self):
        add_token_to_account(self.route.account, self.order.as_token_amount)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_multiple_payments_is_not_open(self):
        partial_payment_amount = self.order.as_token_amount * 0.5
        first_tx = add_token_to_account(self.route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=first_tx.blockchainpayment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

        second_tx = add_token_to_account(self.route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=second_tx.blockchainpayment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_confirmed_payment_is_not_open(self):
        tx = add_token_to_account(self.route.account, self.order.as_token_amount)
        PaymentConfirmation.objects.create(payment=tx.blockchainpayment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())


__all__ = ["PaymentOrderManagerTestCase"]
