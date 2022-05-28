from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from hub20.apps.core.factories.tokens import StableTokenFactory
from hub20.apps.core.factories.users import UserFactory
from hub20.apps.ethereum.factories.tokens import Erc20TokenFactory, EtherFactory


class TokenViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.token_list_url = reverse("token-list")

    def _get_token_url(self, token):
        return reverse("token-detail", kwargs={"pk": token.pk})

    def _get_token_info_url(self, token):
        return f"{self._get_token_url(token)}/info"

    def test_anonymous_user_can_see_token_list(self):
        Erc20TokenFactory()
        EtherFactory()

        response = self.client.get(self.token_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_can_find_by_name_first_letters(self):
        Erc20TokenFactory(name="Example Search")
        success_response = self.client.get(self.token_list_url, dict(search="exam"))
        self.assertEqual(len(success_response.data), 1)

        bad_response = self.client.get(self.token_list_url, dict(search="xyz"))
        self.assertEqual(len(bad_response.data), 0)

    def test_can_find_by_symbol(self):
        Erc20TokenFactory(symbol="GOOD")
        success_response = self.client.get(self.token_list_url, dict(search="gOOd"))
        self.assertEqual(len(success_response.data), 1)

        bad_response = self.client.get(self.token_list_url, dict(search="BAD"))
        self.assertEqual(len(bad_response.data), 0)

    def test_can_filter_native_tokens(self):
        EtherFactory()
        response = self.client.get(self.token_list_url, dict(native=True))
        self.assertEqual(len(response.data), 1)

    def test_can_filter_stable_tokens(self):
        StableTokenFactory()
        response = self.client.get(self.token_list_url, dict(stable=True))
        self.assertEqual(len(response.data), 1)

    def test_can_filter_by_fiat_code(self):
        StableTokenFactory(currency="EUR")

        good_response = self.client.get(self.token_list_url, dict(fiat="EUR"))
        self.assertEqual(len(good_response.data), 1)

        bad_response = self.client.get(self.token_list_url, dict(fiat="USD"))
        self.assertEqual(len(bad_response.data), 0)

    def test_anonymous_user_can_see_token(self):
        token = Erc20TokenFactory()
        token_url = self._get_token_url(token)
        response = self.client.get(token_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["address"], str(token.address))

    def test_can_see_token_info(self):
        stable_pair = StableTokenFactory(currency="INR")
        token = stable_pair.token
        response = self.client.get(self._get_token_info_url(token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["is_stable"], True)
        self.assertEqual(response.data["tracks_currency"], "INR")


class TokenManagementViewTestCase(TestCase):
    def setUp(self):
        self.token = Erc20TokenFactory()
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_user_can_not_create_new_token(self):
        response = self.client.post(
            reverse("token-list"), data={"chain_id": self.token.chain_id, "address": "0xdeadbeef"}
        )
        self.assertEqual(response.status_code, 405)

    def test_user_can_add_existing_token_to_personal_list(self):
        token_data_response = self.client.get(
            reverse("token-detail", kwargs={"pk": self.token.pk})
        )
        token_url = token_data_response.data["url"]
        response = self.client.post(reverse("user-token-list"), data={"token": token_url})
        self.assertEqual(response.status_code, 201)


__all__ = ["TokenViewSetTestCase", "TokenManagementViewTestCase"]
