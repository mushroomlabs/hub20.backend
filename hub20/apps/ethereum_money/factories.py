import factory
from factory import fuzzy

from hub20.apps.blockchain.factories import (
    EthereumProvider,
    SyncedChainFactory,
    TransactionDataFactory,
    TransactionFactory,
)
from hub20.apps.ethereum_money.client import encode_transfer_data
from hub20.apps.ethereum_money.models import EthereumToken, EthereumTokenAmount

factory.Faker.add_provider(EthereumProvider)


class EthereumCurrencyFactory(factory.django.DjangoModelFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    is_listed = True


class ETHFactory(EthereumCurrencyFactory):
    name = fuzzy.FuzzyChoice(choices=["Ethereum"])
    symbol = fuzzy.FuzzyChoice(choices=["ETH"])
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
            "logs": [encode_transfer_data(obj.to_address, obj.amount)],
        }
    )

    class Params:
        gas_used = factory.fuzzy.FuzzyInteger(50000, 200000)
        amount = factory.SubFactory(Erc20TokenAmountFactory)


class Erc20TransferFactory(TransactionFactory):
    class Params:
        recipient = factory.Faker("ethereum_address")
        amount = factory.SubFactory(Erc20TokenAmountFactory)
        to_address = factory.LazyAttribute(lambda obj: obj.amount.currency.address)


__all__ = [
    "ETHFactory",
    "Erc20TokenFactory",
    "EthereumTokenValueModelFactory",
    "Erc20TokenValueModelFactory",
    "Erc20TokenAmountFactory",
    "EtherAmountFactory",
    "Erc20TransferFactory",
]
