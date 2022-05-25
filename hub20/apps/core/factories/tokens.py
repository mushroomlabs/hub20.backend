import factory
from factory import fuzzy

from ..models.tokens import BaseToken, TokenAmount


class BaseTokenFactory(factory.django.DjangoModelFactory):
    is_listed = True
    name = factory.Sequence(lambda n: f"Cryptocurrency #{n:02n}")
    symbol = factory.Sequence(lambda n: f"TOKEN{n:02n}")

    class Meta:
        model = BaseToken


class TokenValueModelFactory(factory.django.DjangoModelFactory):
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SubFactory(BaseTokenFactory)


class TokenAmountFactory(factory.Factory):
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SubFactory(BaseTokenFactory)

    class Meta:
        model = TokenAmount


__all__ = ["BaseTokenFactory", "TokenValueModelFactory", "TokenAmountFactory"]
