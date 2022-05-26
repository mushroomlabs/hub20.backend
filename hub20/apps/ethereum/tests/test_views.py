from django.test import TestCase
from rest_framework.reverse import reverse

from hub20.apps.core.factories import CheckoutFactory

from ..models import BlockchainPaymentRoute


class CheckoutRoutesViewTestCase(TestCase):
    def setUp(self):
        self.checkout = CheckoutFactory()

    def test_can_add_route(self):
        url = reverse("checkout-routes-list", kwargs={"checkout_pk": self.checkout.pk})

        post_data = {"network": BlockchainPaymentRoute.NETWORK}
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 201, response.data)

    def test_can_not_open_multiple_routes_on_same_network(self):
        url = reverse("checkout-routes-list", kwargs={"checkout_pk": self.checkout.pk})

        post_data = {"network": BlockchainPaymentRoute.NETWORK}
        first_route_response = self.client.post(url, post_data)
        self.assertEqual(first_route_response.status_code, 201, first_route_response.data)

        second_route_response = self.client.post(url, post_data)
        self.assertEqual(second_route_response.status_code, 400, first_route_response.data)


__all__ = ["CheckoutRoutesViewTestCase"]
