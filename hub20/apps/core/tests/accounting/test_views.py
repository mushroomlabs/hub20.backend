from decimal import Decimal

from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.core import factories


class TokenBalanceViewTestCase(TestCase):
    def setUp(self):
        self.token = factories.Erc20TokenFactory()
        self.user = factories.UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        factories.Erc20TokenPaymentConfirmationFactory(
            payment__route__deposit__user=self.user,
            payment__currency=self.token,
            payment__amount=10,
        )

    def test_balance_list_includes_token(self):
        response = self.client.get(reverse("balance-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_balance_view(self):
        response = self.client.get(
            reverse(
                "balance-detail",
                kwargs={"chain_id": self.token.chain_id, "address": self.token.address},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["amount"]), 10)


__all__ = ["TokenBalanceViewTestCase"]
