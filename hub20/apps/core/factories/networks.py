import factory

from ..models import PaymentNetwork


class PaymentNetworkFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Test Payment Network #{n:02n}")
    slug = factory.Sequence(lambda n: f"pay-{n:02n}")

    class Meta:
        model = PaymentNetwork
        django_get_or_create = ("name", "slug")


__all__ = ["PaymentNetworkFactory"]
