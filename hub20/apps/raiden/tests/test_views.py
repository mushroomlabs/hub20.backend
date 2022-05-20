from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from hub20.apps.raiden import factories


class BaseRaidenAdminViewTestCase(TestCase):
    def setUp(self):
        self.admin = factories.AdminUserFactory()
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
        user = factories.UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(self.access_url)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_see_raiden_endpoint(self):
        response = self.client.get(self.access_url)
        self.assertEqual(response.status_code, 200)


class ChannelViewTestCase(BaseRaidenAdminViewTestCase):
    def setUp(self):
        self.channel = factories.ChannelFactory()

    def test_can_get_deposit_url(self):
        kwargs = {"raiden_pk": self.channel.raiden.id, "channel_pk": self.channel.id}
        url = reverse("raiden-channel-deposit-list", kwargs=kwargs)
        self.assertTrue(url.endswith(f"channels/{self.channel.id}/deposits"))

    def test_can_get_withdrawal_url(self):
        kwargs = {"raiden_pk": self.channel.raiden.id, "channel_pk": self.channel.id}
        url = reverse("raiden-channel-withdrawal-list", kwargs=kwargs)
        self.assertTrue(url.endswith(f"channels/{self.channel.id}/withdrawals"))


__all__ = ["RaidenNodeViewTestCase", "ChannelViewTestCase"]
