from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from hub20.apps.core.factories.users import AdminUserFactory, UserFactory
from hub20.apps.raiden import factories


class BaseRaidenAdminViewTestCase(TestCase):
    def setUp(self):
        self.admin = AdminUserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.raiden = factories.RaidenFactory()
        self.access_url = reverse("raiden-detail", kwargs={"pk": self.raiden.pk})


class RaidenNodeViewTestCase(BaseRaidenAdminViewTestCase):
    def test_anonymous_user_can_not_access_endpoints(self):
        client = APIClient()
        response = client.get(self.access_url)
        self.assertEqual(response.status_code, 401)

    def test_regular_user_can_not_access_endpoints(self):
        user = UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(self.access_url)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_see_raiden_endpoint(self):
        response = self.client.get(self.access_url)
        self.assertEqual(response.status_code, 200)


__all__ = ["RaidenNodeViewTestCase"]
