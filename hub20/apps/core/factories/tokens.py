import factory

from hub20.apps.core.models.tokens import BaseToken, TokenList, UserTokenList


class BaseTokenFactory(factory.django.DjangoModelFactory):
    is_listed = True
    name = factory.Sequence(lambda n: f"Cryptocurrency #{n:02n}")
    symbol = factory.Sequence(lambda n: f"TOKEN{n:02n}")

    class Meta:
        model = BaseToken


class BaseTokenListFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Token List #{n:02}")
    description = factory.Sequence(lambda n: f"Description for token list #{n:02}")

    @factory.post_generation
    def tokens(self, create, tokens, **kw):
        if not create:
            return

        if tokens:
            for token in tokens:
                self.tokens.add(token)


class TokenListFactory(BaseTokenListFactory):
    url = factory.Sequence(lambda n: f"http://tokenlist{n:02}.example.com")

    class Meta:
        model = TokenList


class UserTokenListFactory(BaseTokenListFactory):
    class Meta:
        model = UserTokenList


__all__ = ["BaseTokenFactory", "BaseTokenListFactory", "TokenListFactory", "UserTokenListFactory"]
