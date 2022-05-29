from decimal import Decimal

from django.test import TestCase

from hub20.apps.core.factories.tokens import TokenAmountFactory


class TokenAmountTestCase(TestCase):
    def setUp(self):
        self.token_amount = TokenAmountFactory()
        self.token = self.token_amount.currency

    def test_can_multiply_by_scalar(self):
        self.token_amount * 2

    def test_can_multiply_by_decimal(self):
        self.token_amount * Decimal("2.5")

    def test_can_multiply_by_float(self):
        self.token_amount * 2.5

    def test_can_add_with_another_token(self):
        other_amount = TokenAmountFactory(currency=self.token)
        token_sum = other_amount + self.token_amount
        self.assertEqual(other_amount.amount + self.token_amount.amount, token_sum.amount)


__all__ = ["TokenAmountTestCase"]
