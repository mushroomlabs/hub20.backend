from django.contrib.sites.models import Site
from django.db import models
from model_utils.managers import InheritanceManager, QueryManager

from .base import BaseModel


class PaymentNetwork(BaseModel):
    name = models.CharField(max_length=300, unique=True)
    description = models.TextField(null=True)
    objects = InheritanceManager()

    @property
    def type(self) -> str:
        return self._meta.app_config.network_name

    def supports_token(self, token) -> bool:
        return False

    class Meta:
        ordering = ("name",)


class InternalPaymentNetwork(PaymentNetwork):
    site = models.OneToOneField(Site, on_delete=models.PROTECT, related_name="treasury")

    def supports_token(self, token) -> bool:
        return token.is_listed


class PaymentNetworkProvider(BaseModel):
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
