import factory
from django.contrib.sites.models import Site

from ..models import InternalPaymentNetwork, PaymentNetwork


class PaymentNetworkFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Test Payment Network #{n:02n}")

    class Meta:
        model = PaymentNetwork
        django_get_or_create = ("name",)


class InternalPaymentNetworkFactory(factory.django.DjangoModelFactory):
    name = "Internal"
    site = factory.LazyAttribute(lambda o: Site.objects.get_current())

    class Meta:
        model = InternalPaymentNetwork


__all__ = ["PaymentNetworkFactory", "InternalPaymentNetworkFactory"]
