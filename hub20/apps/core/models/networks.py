from django.contrib.sites.models import Site
from django.db import models
from model_utils.managers import InheritanceManager, QueryManager


class PaymentNetwork(models.Model):
    name = models.CharField(max_length=300, unique=True)
    description = models.TextField(null=True)

    @property
    def type(self):
        return self._meta.label_lower


class InternalPaymentNetwork(PaymentNetwork):
    site = models.OneToOneField(Site, on_delete=models.PROTECT, related_name="treasury")


class PaymentNetworkProvider(models.Model):
    is_active = models.BooleanField(default=True)
    synced = models.BooleanField(default=False)
    connected = models.BooleanField(default=False)

    objects = InheritanceManager()
    active = QueryManager(is_active=True)
    available = QueryManager(synced=True, connected=True, is_active=True)

    @property
    def is_online(self):
        return self.connected and self.synced


__all__ = ["PaymentNetwork", "InternalPaymentNetwork", "PaymentNetworkProvider"]
