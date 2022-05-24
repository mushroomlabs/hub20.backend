from django.test import TestCase

from hub20.apps.core.factories import Erc20TokenPaymentOrderFactory
from hub20.apps.core.models.payments import PaymentConfirmation
from hub20.apps.core.tests.base import add_token_to_account

from ..models import BlockchainPaymentRoute


class PaymentOrderManagerTestCase(TestCase):
    def setUp(self):
        self.order = Erc20TokenPaymentOrderFactory(
            currency=self.raiden_channel.token_network.token
        )

    def test_order_with_partial_payment_is_open(self):
        route = BlockchainPaymentRoute.make(deposit=self.order)
        partial_payment_amount = self.order.as_token_amount * 0.5
        tx = add_token_to_account(route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=tx.blockchainpayment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_unconfirmed_payment_is_open(self):
        route = BlockchainPaymentRoute.make(deposit=self.order)
        add_token_to_account(route.account, self.order.as_token_amount)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_multiple_payments_is_not_open(self):
        route = BlockchainPaymentRoute.make(deposit=self.order)
        partial_payment_amount = self.order.as_token_amount * 0.5
        first_tx = add_token_to_account(route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=first_tx.blockchainpayment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

        second_tx = add_token_to_account(route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=second_tx.blockchainpayment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_confirmed_payment_is_not_open(self):
        route = BlockchainPaymentRoute.make(deposit=self.order)
        tx = add_token_to_account(route.account, self.order.as_token_amount)
        PaymentConfirmation.objects.create(payment=tx.blockchainpayment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())


__all__ = ["PaymentOrderManagerTestCase"]
