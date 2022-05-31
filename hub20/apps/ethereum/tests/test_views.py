from django.test import TestCase
from rest_framework.reverse import reverse

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


__all__ = ["CheckoutRoutesViewTestCase"]
