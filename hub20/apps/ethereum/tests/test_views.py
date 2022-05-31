from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from ..factories.checkout import Erc20TokenCheckoutFactory
from ..factories.networks import BlockchainPaymentNetworkFactory


class CheckoutRoutesViewTestCase(TestCase):
    def setUp(self):
        self.checkout = Erc20TokenCheckoutFactory()
        self.network = BlockchainPaymentNetworkFactory()
        network_url = reverse("network-detail", kwargs={"pk": self.network.pk})
        self.post_data = {"network": network_url}
        self.url = reverse("checkout-routes-list", kwargs={"checkout_pk": self.checkout.pk})

    def test_can_add_route(self):
        response = self.client.post(self.url, self.post_data)
        self.assertEqual(response.status_code, 201, response.data)

    def test_can_not_open_multiple_routes_on_same_network(self):
        first_route_response = self.client.post(self.url, self.post_data)
        self.assertEqual(first_route_response.status_code, 201, first_route_response.data)

        second_route_response = self.client.post(self.url, self.post_data)
        self.assertEqual(second_route_response.status_code, 400, second_route_response.data)


class BlockchainPaymentNetworkViewTestCase(TestCase):
    def setUp(self):
        self.blockchain_network = BlockchainPaymentNetworkFactory()
        self.client = APIClient()

    def test_endpoint_to_list_networks(self):
        response = self.client.get(reverse("network-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_filter_on_list_endpoint(self):
        response = self.client.get(reverse("network-list"), {"available": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_endpoint_to_retrieve_network(self):
        response = self.client.get(
            reverse("network-detail", kwargs={"pk": self.blockchain_network.pk})
        )
        self.assertEqual(response.status_code, 200)


__all__ = ["CheckoutRoutesViewTestCase", "BlockchainPaymentNetworkViewTestCase"]
