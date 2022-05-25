from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.core.factories import (
    BaseTokenFactory,
    CheckoutFactory,
    StoreFactory,
    TokenAmountFactory,
    UserFactory,
)


class StoreTestCase(TestCase):
    def setUp(self):
        self.store = StoreFactory()

    def test_store_rsa_keys_are_valid_pem(self):
        self.assertIsNotNone(self.store.rsa.pk)
        self.assertTrue(type(self.store.rsa.public_key_pem) is str)
        self.assertTrue(type(self.store.rsa.private_key_pem) is str)

        self.assertTrue(self.store.rsa.public_key_pem.startswith("-----BEGIN PUBLIC KEY-----"))
        self.assertTrue(
            self.store.rsa.private_key_pem.startswith("-----BEGIN RSA PRIVATE KEY-----")
        )


class CheckoutTestCase(TestCase):
    def setUp(self):
        self.checkout = CheckoutFactory()
        self.checkout.store.accepted_token_list.tokens.add(self.checkout.order.currency)

    def test_checkout_user_and_store_owner_are_the_same(self):
        self.assertEqual(self.checkout.store.owner, self.checkout.order.user)

    def test_checkout_currency_must_be_accepted_by_store(self):
        self.checkout.clean()

        self.checkout.store.accepted_token_list.tokens.clear()
        with self.assertRaises(ValidationError):
            self.checkout.clean()


class StoreViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.store = StoreFactory()

    def test_anonymous_user_can_see_store(self):
        url = reverse("store-detail", kwargs={"pk": self.store.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.store.id))


class UserStoreViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.store = StoreFactory()

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
        another_user = UserFactory()
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


class CheckoutViewTestCase(TestCase):
    def setUp(self):
        self.token = BaseTokenFactory()
        self.store = StoreFactory(accepted_token_list__tokens=[self.token])

    def test_can_create_checkout_via_api(self):
        amount = TokenAmountFactory(currency=self.token)

        url = reverse("checkout-list")

        post_data = {
            "amount": amount.amount,
            "token": reverse(
                "token-detail",
                kwargs=dict(address=self.token.address, chain_id=self.token.chain_id),
            ),
            "store": self.store.id,
            "reference": "API Test",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 201, response.data)

    def test_can_not_delete_checkout(self):
        checkout = CheckoutFactory(store=self.store)
        url = reverse("checkout-detail", kwargs={"pk": checkout.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405)


__all__ = [
    "StoreTestCase",
    "CheckoutTestCase",
    "StoreViewTestCase",
    "UserStoreViewTestCase",
    "CheckoutViewTestCase",
]
