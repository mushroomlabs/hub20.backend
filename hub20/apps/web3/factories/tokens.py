import factory
from factory import fuzzy

from hub20.apps.core.factories.tokens import BaseTokenFactory, TokenValueModelFactory
from hub20.apps.core.models.tokens import StableTokenPair, TokenAmount, WrappedToken

from ..client import encode_transfer_data
from ..models import Erc20Token, NativeToken, TransferEvent
from .blockchain import SyncedChainFactory, TransactionDataFactory, TransactionFactory


class EtherFactory(BaseTokenFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    name = factory.Sequence(lambda n: f"Native Token #{n:02n}")
    symbol = factory.Sequence(lambda n: f"ETH{n:02n}")

    class Meta:
        model = NativeToken
        django_get_or_create = ("chain",)


class Erc20TokenFactory(BaseTokenFactory):
    name = factory.Sequence(lambda n: f"ERC20 Token #{n:03}")
    symbol = factory.Sequence(lambda n: f"ERC20_{n:03}")
    address = factory.Faker("ethereum_address")

    class Meta:
        model = Erc20Token


class WrappedEtherFactory(factory.django.DjangoModelFactory):
    wrapper = factory.SubFactory(Erc20TokenFactory)
    wrapped = factory.SubFactory(EtherFactory)

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


class EtherValueModelFactory(TokenValueModelFactory):
    currency = factory.SubFactory(EtherFactory)


class Erc20TokenValueModelFactory(TokenValueModelFactory):
    currency = factory.SubFactory(Erc20TokenFactory)


class Erc20TokenAmountFactory(factory.Factory):
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SubFactory(Erc20TokenFactory)

    class Meta:
        model = TokenAmount


class EtherAmountFactory(factory.Factory):
    amount = fuzzy.FuzzyDecimal(0, 10, precision=6)
    currency = factory.SubFactory(EtherFactory)

    class Meta:
        model = TokenAmount


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


__all__ = [
    "EtherFactory",
    "Erc20TokenFactory",
    "WrappedEtherFactory",
    "WrappedTokenFactory",
    "StableTokenFactory",
    "EtherValueModelFactory",
    "Erc20TokenValueModelFactory",
    "Erc20TokenAmountFactory",
    "EtherAmountFactory",
    "Erc20TransactionDataFactory",
    "Erc20TransactionFactory",
    "Erc20TransferEventFactory",
]
