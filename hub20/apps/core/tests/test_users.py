from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.core import factories


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


__all__ = ["UserViewTestCase"]
