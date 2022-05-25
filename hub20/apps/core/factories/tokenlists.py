import factory

from ..models.tokenlists import TokenList, UserTokenList


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


__all__ = ["BaseTokenListFactory", "TokenListFactory", "UserTokenListFactory"]
