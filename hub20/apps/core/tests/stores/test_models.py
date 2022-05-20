from django.core.exceptions import ValidationError
from django.test import TestCase

from hub20.apps.core.factories import CheckoutFactory, StoreFactory


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


__all__ = ["StoreTestCase", "CheckoutTestCase"]
