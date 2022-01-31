from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from hub20.apps.ethereum_money import factories


class TokenViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.token_list_url = reverse("token-list")

    def _get_token_url(self, token):
        return reverse(
            "token-detail",
            kwargs={"address": token.address, "chain_id": token.chain_id},
        )

    def _get_token_info_url(self, token):
        return f"{self._get_token_url(token)}/info"

    def test_anonymous_user_can_see_token_list(self):
        factories.Erc20TokenFactory()
        factories.ETHFactory()

        response = self.client.get(self.token_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_can_find_by_name_first_letters(self):
        factories.Erc20TokenFactory(name="Example Search")
        success_response = self.client.get(self.token_list_url, dict(search="exam"))
        self.assertEqual(len(success_response.data), 1)

        bad_response = self.client.get(self.token_list_url, dict(search="xyz"))
        self.assertEqual(len(bad_response.data), 0)

    def test_can_find_by_symbol(self):
        factories.Erc20TokenFactory(symbol="GOOD")
        success_response = self.client.get(self.token_list_url, dict(search="gOOd"))
        self.assertEqual(len(success_response.data), 1)

        bad_response = self.client.get(self.token_list_url, dict(search="BAD"))
        self.assertEqual(len(bad_response.data), 0)

    def test_can_filter_native_tokens(self):
        factories.ETHFactory()
        response = self.client.get(self.token_list_url, dict(native=True))
        self.assertEqual(len(response.data), 1)

    def test_can_filter_stable_tokens(self):
        factories.StableTokenFactory()
        response = self.client.get(self.token_list_url, dict(stable=True))
        self.assertEqual(len(response.data), 1)

    def test_can_filter_by_fiat_code(self):
        factories.StableTokenFactory(currency="EUR")

        good_response = self.client.get(self.token_list_url, dict(fiat="EUR"))
        self.assertEqual(len(good_response.data), 1)

        bad_response = self.client.get(self.token_list_url, dict(fiat="USD"))
        self.assertEqual(len(bad_response.data), 0)

    def test_anonymous_user_can_see_token(self):
        token = factories.Erc20TokenFactory()
        token_url = self._get_token_url(token)
        response = self.client.get(token_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["address"], str(token.address))

    def test_can_see_token_info(self):
        stable_pair = factories.StableTokenFactory(currency="INR")
        token = stable_pair.token
        response = self.client.get(self._get_token_info_url(token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["is_stable"], True)
        self.assertEqual(response.data["tracks_currency"], "INR")


__all__ = ["TokenViewSetTestCase"]
