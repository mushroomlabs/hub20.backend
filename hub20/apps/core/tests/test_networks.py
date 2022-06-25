from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.core.factories import InternalPaymentNetworkFactory


class PaymentNetworkTestCase(TestCase):
    def setUp(self):
        self.hub = InternalPaymentNetworkFactory()


class PaymentNetworkViewTestCase(PaymentNetworkTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_endpoint_to_list_networks(self):
        response = self.client.get(reverse("network-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1, "internal network should be visible on the API")

    def test_filter_on_list_endpoint(self):
        response = self.client.get(reverse("network-list"), {"available": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

    def test_endpoint_to_retrieve_network(self):
        response = self.client.get(reverse("network-detail", kwargs={"pk": self.hub.pk}))
        self.assertEqual(response.status_code, 200)


__all__ = ["PaymentNetworkViewTestCase"]
