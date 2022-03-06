import pytest
from django.test import TestCase

from hub20.apps.core.factories import Erc20TokenPaymentOrderFactory, InternalTransferFactory
from hub20.apps.core.models import (
    BlockchainPaymentRoute,
    PaymentConfirmation,
    PaymentOrder,
    RaidenPaymentRoute,
    Transfer,
    TransferConfirmation,
)
from hub20.apps.ethereum_money.tests.base import add_token_to_account
from hub20.apps.raiden.factories import ChannelFactory


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class PaymentOrderManagerTestCase(BaseTestCase):
    def setUp(self):
        self.raiden_channel = ChannelFactory()
        self.order = Erc20TokenPaymentOrderFactory(
            currency=self.raiden_channel.token_network.token
        )

    def test_order_has_blockchain_route(self):
        self.assertTrue(PaymentOrder.objects.with_blockchain_route().exists())

    def test_order_has_raiden_route(self):
        self.assertTrue(RaidenPaymentRoute.objects.exists())
        with_route = PaymentOrder.objects.with_raiden_route()
        self.assertTrue(with_route.exists())

    def test_order_with_no_payment_is_open(self):
        self.assertTrue(PaymentOrder.objects.unpaid().filter(id=self.order.id).exists())
        self.assertFalse(PaymentOrder.objects.paid().filter(id=self.order.id).exists())

    def test_order_with_partial_payment_is_open(self):
        route = BlockchainPaymentRoute.objects.filter(deposit=self.order).first()
        partial_payment_amount = self.order.as_token_amount * 0.5
        tx = add_token_to_account(route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=tx.blockchainpayment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_unconfirmed_payment_is_open(self):
        route = BlockchainPaymentRoute.objects.filter(deposit=self.order).first()
        add_token_to_account(route.account, self.order.as_token_amount)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_multiple_payments_is_not_open(self):
        route = BlockchainPaymentRoute.objects.filter(deposit=self.order).first()
        partial_payment_amount = self.order.as_token_amount * 0.5
        first_tx = add_token_to_account(route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=first_tx.blockchainpayment)
        self.assertTrue(BlockchainPaymentRoute.objects.open().exists())

        second_tx = add_token_to_account(route.account, partial_payment_amount)
        PaymentConfirmation.objects.create(payment=second_tx.blockchainpayment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())

    def test_order_with_confirmed_payment_is_not_open(self):
        route = BlockchainPaymentRoute.objects.filter(deposit=self.order).first()
        tx = add_token_to_account(route.account, self.order.as_token_amount)
        PaymentConfirmation.objects.create(payment=tx.blockchainpayment)
        self.assertFalse(BlockchainPaymentRoute.objects.open().exists())


class TransferManagerTestCase(BaseTestCase):
    def test_pending_query_manager(self):
        self.transfer = InternalTransferFactory()

        self.assertTrue(Transfer.pending.exists())

        # Confirmed transfers are no longer pending
        TransferConfirmation.objects.create(transfer=self.transfer)
        self.assertTrue(Transfer.confirmed.exists())
        self.assertFalse(Transfer.pending.exists())

        # Another transfer shows up, and already confirmed transfers are out
        another_transfer = InternalTransferFactory()
        self.assertTrue(Transfer.pending.exists())
        self.assertEqual(Transfer.pending.count(), 1)
        self.assertEqual(Transfer.pending.select_subclasses().first(), another_transfer)


__all__ = ["PaymentOrderManagerTestCase", "TransferManagerTestCase"]
