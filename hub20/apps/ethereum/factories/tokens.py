import factory
from web3 import EthereumTesterProvider, Web3

from hub20.apps.core.factories.tokens import (
    BaseTokenFactory,
    StableTokenFactory,
    TokenAmountFactory,
    TokenValueModelFactory,
)
from hub20.apps.core.models.tokens import WrappedToken
from hub20.apps.core.typing import Wei

from ..abi.tokens import EIP20_ABI
from ..models import Erc20Token, NativeToken, TransferEvent
from .blockchain import SyncedChainFactory, TransactionDataFactory, TransactionFactory

w3 = Web3(EthereumTesterProvider())


def encode_transfer_data(address, amount: Wei):
    contract = w3.eth.contract(abi=EIP20_ABI)
    return contract.encodeABI("transfer", [address, amount])


class EtherFactory(BaseTokenFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    name = factory.Sequence(lambda n: f"Native Token #{n:02n}")
    symbol = factory.Sequence(lambda n: f"ETH{n:02n}")

    class Meta:
        model = NativeToken
        django_get_or_create = ("chain",)


class Erc20TokenFactory(BaseTokenFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    name = factory.Sequence(lambda n: f"ERC20 Token #{n:03}")
    symbol = factory.Sequence(lambda n: f"ERC20_{n:03}")
    address = factory.Faker("ethereum_address")

    class Meta:
        model = Erc20Token
        django_get_or_create = ("chain", "address")


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


class Erc20StableTokenFactory(StableTokenFactory):
    token = factory.SubFactory(Erc20TokenFactory)


class EtherValueModelFactory(TokenValueModelFactory):
    currency = factory.SubFactory(EtherFactory)


class Erc20TokenValueModelFactory(TokenValueModelFactory):
    currency = factory.SubFactory(Erc20TokenFactory)


class Erc20TokenAmountFactory(TokenAmountFactory):
    currency = factory.SubFactory(Erc20TokenFactory)


class EtherAmountFactory(TokenAmountFactory):
    currency = factory.SubFactory(EtherFactory)


class Erc20TokenTransactionDataFactory(TransactionDataFactory):
    data = factory.LazyAttribute(
        lambda obj: {
            "from": obj.from_address,
            "to": obj.to_address,
            "status": obj.status,
            "blockNumber": obj.block_number,
            "blockHash": obj.block_hash,
            "gasUsed": obj.gas_used,
            "logs": [encode_transfer_data(obj.recipient, obj.amount.as_wei)],
        }
    )

    class Params:
        recipient = factory.Faker("ethereum_address")
        gas_used = factory.fuzzy.FuzzyInteger(50000, 200000)
        amount = factory.SubFactory(Erc20TokenAmountFactory)
        to_address = factory.LazyAttribute(lambda obj: obj.amount.currency.subclassed.address)


class Erc20TokenTransactionFactory(TransactionFactory):
    class Params:
        recipient = factory.Faker("ethereum_address")
        amount = factory.SubFactory(Erc20TokenAmountFactory)
        to_address = factory.LazyAttribute(lambda obj: obj.amount.currency.subclassed.address)


class Erc20TokenTransferEventFactory(factory.django.DjangoModelFactory):
    transaction = factory.SubFactory(
        Erc20TokenTransactionFactory,
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
    "encode_transfer_data",
    "EtherFactory",
    "Erc20TokenFactory",
    "WrappedEtherFactory",
    "WrappedTokenFactory",
    "EtherValueModelFactory",
    "Erc20TokenValueModelFactory",
    "Erc20TokenAmountFactory",
    "EtherAmountFactory",
    "Erc20StableTokenFactory",
    "Erc20TokenTransactionDataFactory",
    "Erc20TokenTransactionFactory",
    "Erc20TokenTransferEventFactory",
]
