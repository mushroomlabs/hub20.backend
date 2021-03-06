from django.test import TestCase

from hub20.apps.core.factories import PaymentOrderFactory
from hub20.apps.core.models.payments import PaymentOrder


class PaymentOrderManagerTestCase(TestCase):
    def setUp(self):
        self.order = PaymentOrderFactory()

    def test_order_with_no_payment_is_open(self):
        self.assertTrue(PaymentOrder.objects.unpaid().filter(id=self.order.id).exists())
        self.assertFalse(PaymentOrder.objects.paid().filter(id=self.order.id).exists())


__all__ = ["PaymentOrderManagerTestCase"]
