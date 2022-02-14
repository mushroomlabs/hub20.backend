from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from hub20.apps.blockchain.factories import FAKER
from hub20.apps.core import factories
from hub20.apps.core.factories import (
    Erc20TokenBlockchainPaymentFactory,
    Erc20TokenPaymentConfirmationFactory,
)
from hub20.apps.ethereum_money.factories import Erc20TokenAmountFactory, Erc20TokenFactory


class StoreViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.store = factories.StoreFactory()

    def test_anonymous_user_can_see_store(self):
        url = reverse("store-detail", kwargs={"pk": self.store.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.store.id))


class UserStoreViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.store = factories.StoreFactory()

    def test_anonymous_user_can_not_list_stores(self):
        url = reverse("user-store-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_store_owner_can_see_store(self):
        url = reverse("store-detail", kwargs={"pk": self.store.pk})
        self.client.force_authenticate(user=self.store.owner)
        self.client.get(url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.store.id))

    def test_non_owner_can_not_see_store(self):
        url = reverse("user-store-detail", kwargs={"pk": self.store.pk})
        another_user = factories.UserFactory()
        self.client.force_authenticate(user=another_user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_checkout_webhook_url_is_not_required_to_update(self):
        url = reverse("user-store-detail", kwargs={"pk": self.store.pk})
        self.client.force_authenticate(user=self.store.owner)
        response = self.client.get(url)

        data = response.data
        data.pop("checkout_webhook_url", None)
        data["name"] = "Store without webhook"

        response = self.client.put(url, data)
        self.assertEqual(response.status_code, 200)

    def test_checkout_webhook_url_is_not_required_to_create(self):
        url = reverse("user-store-list")
        self.client.force_authenticate(user=self.store.owner)
        response = self.client.get(url)

        data = response.data[0]
        data.pop("checkout_webhook_url", None)
        data["name"] = "New Store without webhook"
        data["site_url"] = "http://cloned.stored.example.com"

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 201)


class UserViewTestCase(TestCase):
    def setUp(self):
        self.superuser = factories.UserFactory(is_superuser=True, is_staff=True)
        self.staff_user = factories.UserFactory(is_staff=True)
        self.inactive_user = factories.UserFactory(is_active=False)
        self.client = APIClient()
        self.url = reverse("users-list")

    def test_search_shows_only_active_users(self):
        regular_username = "one_regular_user"
        active_user = factories.UserFactory(username=regular_username)
        self.client.force_authenticate(user=active_user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["username"], regular_username)

    def test_filter_query(self):
        one_user = factories.UserFactory(username="one_user", email="hub20@one.example.com")
        factories.UserFactory(username="another_user", email="hub20@another.example.com")

        self.client.force_authenticate(user=one_user)

        one_query_response = self.client.get(self.url, {"search": "one"})
        self.assertEqual(len(one_query_response.data), 1)

        another_query_response = self.client.get(self.url, {"search": "another"})
        self.assertEqual(len(another_query_response.data), 1)

        email_query_response = self.client.get(self.url, {"search": "hub20"})
        self.assertEqual(len(email_query_response.data), 2)


class TokenBalanceViewTestCase(TestCase):
    def setUp(self):
        self.token = Erc20TokenFactory()
        self.user = factories.UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        Erc20TokenPaymentConfirmationFactory(
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


class TransferTestCase(TestCase):
    def setUp(self):
        self.user = factories.UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.token = Erc20TokenFactory()
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

        Erc20TokenPaymentConfirmationFactory(
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


class CheckoutViewTestCase(TestCase):
    def setUp(self):
        self.token = Erc20TokenFactory()
        self.store = factories.StoreFactory(accepted_token_list__tokens=[self.token])

    def test_can_create_checkout_via_api(self):
        amount = Erc20TokenAmountFactory(currency=self.token)

        url = reverse("checkout-list")
        post_data = {
            "amount": amount.amount,
            "token": reverse(
                "token-detail",
                kwargs=dict(address=amount.currency.address, chain_id=amount.currency.chain_id),
            ),
            "store": self.store.id,
            "external_identifier": "API Test",
        }

        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 201, response.data)

    def test_can_not_delete_checkout(self):
        checkout = factories.CheckoutFactory(store=self.store)
        url = reverse("checkout-detail", kwargs={"pk": checkout.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405)

    def test_payment_serializer(self):
        checkout = factories.CheckoutFactory(store=self.store)
        route = checkout.routes.select_subclasses().first()

        Erc20TokenBlockchainPaymentFactory(route=route)

        url = reverse("checkout-detail", kwargs={"pk": checkout.pk})
        response = self.client.get(url)

        self.assertEqual(len(response.data["payments"]), 1)

        payment = response.data["payments"][0]

        self.assertTrue("transaction" in payment)
        self.assertTrue("block" in payment)


__all__ = ["StoreViewTestCase", "CheckoutViewTestCase"]
