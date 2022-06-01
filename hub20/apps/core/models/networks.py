from django.contrib.sites.models import Site
from django.db import models
from model_utils.managers import InheritanceManager

from .base import BaseModel, PolymorphicModelMixin


class ActiveProviderManager(InheritanceManager):
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(is_active=True)


class AvailableProviderManager(InheritanceManager):
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(is_active=True, synced=True, connected=True)


class PaymentNetwork(BaseModel, PolymorphicModelMixin):
    name = models.CharField(max_length=300, unique=True)
    description = models.TextField(null=True)
    objects = InheritanceManager()

    @property
    def type(self) -> str:
        return self.subclassed._meta.app_config.network_name

    def supports_token(self, token) -> bool:
        return False

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("name",)


class InternalPaymentNetwork(PaymentNetwork):
    site = models.OneToOneField(Site, on_delete=models.PROTECT, related_name="treasury")

    def supports_token(self, token) -> bool:
        return token.is_listed


class PaymentNetworkProvider(BaseModel, PolymorphicModelMixin):
    SYNC_INTERVAL = 30  # in seconds

    is_active = models.BooleanField(default=True)
    synced = models.BooleanField(default=False)
    connected = models.BooleanField(default=False)
    network = models.ForeignKey(PaymentNetwork, on_delete=models.CASCADE, related_name="providers")

    objects = InheritanceManager()
    active = ActiveProviderManager()
    available = AvailableProviderManager()

    @property
    def is_online(self):
        return self.connected and self.synced

    @property
    def sync_interval(self):
        return self.SYNC_INTERVAL

    def activate(self):
        self.is_active = True
        self.save()

    def sync(self):
        pass

    def check_open_payments(self):
        pass

    def execute_transfers(self):
        pass

    def __str__(self):
        return f"{self.subclassed.__class__.__name__} for {self.network.subclassed.name}"


__all__ = ["PaymentNetwork", "InternalPaymentNetwork", "PaymentNetworkProvider"]
