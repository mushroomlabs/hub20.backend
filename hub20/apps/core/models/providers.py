from typing import TypeVar

from django.db import models
from model_utils.managers import InheritanceManager

from .base import BaseModel, PolymorphicModelMixin
from .networks import PaymentNetwork


class ActiveProviderManager(InheritanceManager):
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(is_active=True)


class AvailableProviderManager(InheritanceManager):
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(is_active=True, synced=True, connected=True)


class PaymentNetworkProvider(BaseModel, PolymorphicModelMixin):
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


PaymentNetworkProvider_T = TypeVar("PaymentNetworkProvider_T", bound=PaymentNetworkProvider)


__all__ = [
    "PaymentNetworkProvider",
    "PaymentNetworkProvider_T",
]
