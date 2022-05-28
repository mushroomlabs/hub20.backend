import factory
from django.conf import settings
from django.contrib.sites.models import Site

from ..models import InternalPaymentNetwork, PaymentNetwork


class SiteFactory(factory.django.DjangoModelFactory):
    id = settings.SITE_ID
    name = "Test Site"
    domain = "hub20.example.com"

    class Meta:
        model = Site
        django_get_or_create = ("id",)


class PaymentNetworkFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Test Payment Network #{n:02n}")

    class Meta:
        model = PaymentNetwork
        django_get_or_create = ("name",)


class InternalPaymentNetworkFactory(factory.django.DjangoModelFactory):
    name = "Internal"
    site = factory.SubFactory(SiteFactory)

    class Meta:
        model = InternalPaymentNetwork
        django_get_or_create = ("name",)


__all__ = ["PaymentNetworkFactory", "InternalPaymentNetworkFactory"]
