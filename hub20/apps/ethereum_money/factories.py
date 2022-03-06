import factory
from factory import fuzzy

from hub20.apps.blockchain.factories import (
    EthereumProvider,
    SyncedChainFactory,
    TransactionDataFactory,
    TransactionFactory,
)
from hub20.apps.ethereum_money.client import encode_transfer_data
from hub20.apps.ethereum_money.models import (
    EthereumToken,
    EthereumTokenAmount,
    StableTokenPair,
    TokenList,
    TransferEvent,
    UserTokenList,
    WrappedToken,
)

factory.Faker.add_provider(EthereumProvider)


class EthereumCurrencyFactory(factory.django.DjangoModelFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    is_listed = True


class ETHFactory(EthereumCurrencyFactory):
    name = "Ether"
    symbol = "ETH"
    address = EthereumToken.NULL_ADDRESS

    class Meta:
        model = EthereumToken
        django_get_or_create = ("chain", "name", "address")


class Erc20TokenFactory(EthereumCurrencyFactory):
    name = factory.Sequence(lambda n: f"ERC20 Token #{n:03}")
    symbol = factory.Sequence(lambda n: f"TOK#{n:03}")
    address = factory.Faker("ethereum_address")

    class Meta:
        model = EthereumToken


class WrappedEtherFactory(factory.django.DjangoModelFactory):
    wrapper = factory.SubFactory(Erc20TokenFactory)
    wrapped = factory.SubFactory(ETHFactory)

    class Meta:
        model = WrappedToken


class WrappedTokenFactory(factory.django.DjangoModelFactory):
    wrapper = factory.SubFactory(Erc20TokenFactory)
    wrapped = factory.SubFactory(Erc20TokenFactory)

    class Meta:
        model = WrappedToken


class StableTokenFactory(factory.django.DjangoModelFactory):
    token = factory.SubFactory(Erc20TokenFactory)
    currency = factory.Iterator(["USD", "EUR", "GBP"])

    class Meta:
        model = StableTokenPair


class EthereumTokenValueModelFactory(factory.django.DjangoModelFactory):
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SubFactory(ETHFactory)


class Erc20TokenValueModelFactory(factory.django.DjangoModelFactory):
    amount = fuzzy.FuzzyDecimal(0, 1000, precision=8)
    currency = factory.SubFactory(Erc20TokenFactory)


class Erc20TokenAmountFactory(factory.Factory):
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SubFactory(Erc20TokenFactory)

    class Meta:
        model = EthereumTokenAmount


class EtherAmountFactory(factory.Factory):
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SubFactory(ETHFactory)

    class Meta:
        model = EthereumTokenAmount


class Erc20TransactionDataFactory(TransactionDataFactory):
    data = factory.LazyAttribute(
        lambda obj: {
            "from": obj.from_address,
            "to": obj.to_address,
            "status": obj.status,
            "blockNumber": obj.block_number,
            "blockHash": obj.block_hash,
            "gasUsed": obj.gas_used,
            "logs": [encode_transfer_data(obj.recipient, obj.amount)],
        }
    )

    class Params:
        recipient = factory.Faker("ethereum_address")
        gas_used = factory.fuzzy.FuzzyInteger(50000, 200000)
        amount = factory.SubFactory(Erc20TokenAmountFactory)
        to_address = factory.LazyAttribute(lambda obj: obj.amount.currency.address)


class Erc20TransactionFactory(TransactionFactory):
    class Params:
        recipient = factory.Faker("ethereum_address")
        amount = factory.SubFactory(Erc20TokenAmountFactory)
        to_address = factory.LazyAttribute(lambda obj: obj.amount.currency.address)


class Erc20TransferEventFactory(factory.django.DjangoModelFactory):
    transaction = factory.SubFactory(
        Erc20TransactionFactory,
        amount=factory.SelfAttribute("..transfer_amount"),
        recipient=factory.SelfAttribute("..recipient"),
        to_address=factory.SelfAttribute("..sender"),
    )
    amount = factory.SelfAttribute("transfer_amount.amount")
    currency = factory.SelfAttribute("transfer_amount.currency")
    recipient = factory.Faker("ethereum_address")
    sender = factory.Faker("ethereum_address")
    log_index = 0

    class Meta:
        model = TransferEvent

    class Params:
        transfer_amount = factory.SubFactory(Erc20TokenAmountFactory)


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


__all__ = [
    "ETHFactory",
    "Erc20TokenFactory",
    "EthereumTokenValueModelFactory",
    "Erc20TokenValueModelFactory",
    "Erc20TokenAmountFactory",
    "EtherAmountFactory",
    "Erc20TransactionDataFactory",
    "Erc20TransactionFactory",
    "Erc20TransferEventFactory",
    "TokenListFactory",
    "WrappedEtherFactory",
    "WrappedTokenFactory",
    "StableTokenFactory",
    "UserTokenListFactory",
]
