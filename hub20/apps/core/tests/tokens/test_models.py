from django.test import TestCase

from hub20.apps.ethereum_money import factories


class TransferEventTestCase(TestCase):
    def setUp(self):
        self.transfer_event = factories.Erc20TransferEventFactory()

    def test_can_get_token_amount(self):
        self.assertIsNotNone(self.transfer_event.as_token_amount)


__all__ = ["TransferEventTestCase"]
