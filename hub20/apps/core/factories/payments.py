import factory
from factory import fuzzy

from ..models import PaymentOrder
from .tokens import BaseTokenFactory
from .users import UserFactory


class PaymentOrderFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory(UserFactory)
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    reference = factory.fuzzy.FuzzyText(length=30, prefix="order-")
    currency = factory.SubFactory(BaseTokenFactory)

    class Meta:
        abstract = False
        model = PaymentOrder


__all__ = ["PaymentOrderFactory"]
