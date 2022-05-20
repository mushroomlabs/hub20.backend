from django.test import TestCase

from hub20.apps.core.factories import Erc20TokenPaymentOrderFactory
from hub20.apps.core.models import PaymentOrder

from ..factories import ChannelFactory
from ..models import RaidenPaymentRoute


class PaymentOrderManagerTestCase(TestCase):
    def setUp(self):
        self.raiden_channel = ChannelFactory()
        self.order = Erc20TokenPaymentOrderFactory(
            currency=self.raiden_channel.token_network.token
        )

    def test_order_can_create_raiden_route(self):
        RaidenPaymentRoute.make(deposit=self.order)
        self.assertTrue(RaidenPaymentRoute.objects.exists())
        orders_with_raiden_route = PaymentOrder.objects.with_route(
            network=RaidenPaymentRoute.NETWORK
        )
        self.assertTrue(orders_with_raiden_route.exists())


__all__ = ["PaymentOrderManagerTestCase"]
