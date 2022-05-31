from decimal import Decimal

from django.test import TestCase

from hub20.apps.core.factories.tokens import BaseTokenFactory, TokenAmountFactory
from hub20.apps.core.models.tokens import BaseToken


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


class TokenModelManagerTestCase(TestCase):
    def setUp(self):
        self.listed_token = BaseTokenFactory(is_listed=True)
        self.unlisted_token = BaseTokenFactory(is_listed=False)

    def test_can_filter_listed_tokens(self):
        self.assertEqual(BaseToken.objects.filter(is_listed=True).count(), 1)
        self.assertEqual(BaseToken.objects.filter(is_listed=False).count(), 1)
        self.assertEqual(BaseToken.objects.count(), 2)

    def test_can_filter_with_tradeable_manager(self):
        self.assertEqual(BaseToken.tradeable.count(), 1)
        self.assertEqual(BaseToken.tradeable.select_subclasses().count(), 1)


__all__ = ["TokenAmountTestCase", "TokenModelManagerTestCase"]
