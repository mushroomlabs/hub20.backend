from typing import TypeVar

from django.contrib.sites.models import Site
from django.db import models
from model_utils.managers import InheritanceManager

from .base import BaseModel, PolymorphicModelMixin


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


PaymentNetwork_T = TypeVar("PaymentNetwork_T", bound=PaymentNetwork)


__all__ = [
    "PaymentNetwork",
    "InternalPaymentNetwork",
    "PaymentNetwork_T",
]
