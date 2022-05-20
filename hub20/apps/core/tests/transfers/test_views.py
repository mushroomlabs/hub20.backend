from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.blockchain.factories import FAKER
from hub20.apps.core import factories


class TransferViewTestCase(TestCase):
    def setUp(self):
        self.user = factories.UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.token = factories.Erc20TokenFactory()
        self.target_address = FAKER.ethereum_address()

    def test_no_balance_returns_error(self):
        response = self.client.post(
            reverse("user-withdrawal-list"),
            {
                "address": self.target_address,
                "payment_network": "blockchain",
                "amount": 10,
                "token": reverse(
                    "token-detail",
                    kwargs=dict(address=self.token.address, chain_id=self.token.chain_id),
                ),
            },
        )
        self.assertEqual(response.status_code, 400)

        self.assertTrue("non_field_errors" in response.data.keys())
        self.assertEqual(len(response.data["non_field_errors"]), 1)

        error_details = response.data["non_field_errors"][0]
        self.assertEqual(error_details.code, "invalid")

    def test_insufficient_balance_returns_error(self):
        TRANSFER_AMOUNT = 10

        factories.Erc20TokenPaymentConfirmationFactory(
            payment__route__deposit__user=self.user,
            payment__currency=self.token,
            payment__amount=TRANSFER_AMOUNT / 2,
        )

        response = self.client.post(
            reverse("user-withdrawal-list"),
            {
                "address": self.target_address,
                "payment_network": "blockchain",
                "amount": TRANSFER_AMOUNT,
                "token": reverse(
                    "token-detail",
                    kwargs=dict(address=self.token.address, chain_id=self.token.chain_id),
                ),
            },
        )
        self.assertEqual(response.status_code, 400)

        self.assertTrue("non_field_errors" in response.data.keys())
        self.assertEqual(len(response.data["non_field_errors"]), 1)

        error_details = response.data["non_field_errors"][0]
        self.assertEqual(error_details.code, "insufficient")


__all__ = ["TransferViewTestCase"]
