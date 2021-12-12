from typing import List

import factory
import factory.fuzzy
from django.utils import timezone
from faker import Faker

from ..app_settings import START_BLOCK_NUMBER
from ..models import BaseEthereumAccount, Block, Chain, Transaction, TransactionLog, Web3Provider
from .providers import EthereumProvider

factory.Faker.add_provider(EthereumProvider)


TEST_CHAIN_ID = 2
FAKER = Faker()
FAKER.add_provider(EthereumProvider)


def find_parent_by_block_number(block):
    return Block.objects.filter(chain=block.chain, number=block.number - 1).first()


def make_parent_hash(block):
    parent = find_parent_by_block_number(block)
    return parent and parent.hash or block.default_parent_hash


class BaseWalletFactory(factory.django.DjangoModelFactory):
    address = factory.Faker("ethereum_address")

    class Meta:
        model = BaseEthereumAccount
        django_get_or_create = ("address",)


class ChainFactory(factory.django.DjangoModelFactory):
    id = TEST_CHAIN_ID
    highest_block = 0

    @factory.post_generation
    def blocks(obj, create, extracted, **kw):
        if not create:
            return

        if not extracted:
            BlockFactory(number=obj.highest_block, chain=obj)
        else:
            for block in extracted:
                obj.blocks.add(block)

    @factory.post_generation
    def providers(obj, create, extracted, **kw):
        if not create:
            return

        if not extracted:
            Web3ProviderFactory(chain=obj)
        else:
            for provider in extracted:
                obj.providers.add(provider)

    class Meta:
        model = Chain
        django_get_or_create = ("id",)


class SyncedChainFactory(ChainFactory):
    highest_block = START_BLOCK_NUMBER

    @factory.post_generation
    def providers(obj, create, extracted, **kw):
        if not create:
            return

        if not extracted:
            SyncedWeb3ProviderFactory(chain=obj)
        else:
            for provider in extracted:
                obj.providers.add(provider)


class BlockFactory(factory.django.DjangoModelFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    hash = factory.Faker("hex64")
    number = factory.Sequence(lambda n: n + START_BLOCK_NUMBER)
    timestamp = factory.LazyAttribute(lambda obj: timezone.now())
    parent_hash = factory.LazyAttribute(lambda obj: make_parent_hash(obj))
    uncle_hashes: List = []

    class Params:
        default_parent_hash = factory.Faker("hex64")

    class Meta:
        model = Block


class TransactionFactory(factory.django.DjangoModelFactory):
    chain = factory.LazyAttribute(lambda obj: obj.block.chain)
    block = factory.SubFactory(BlockFactory)
    hash = factory.Faker("hex64")
    from_address = factory.Faker("ethereum_address")
    to_address = factory.Faker("ethereum_address")
    gas_used = 21000
    gas_price = factory.fuzzy.FuzzyInteger(1e10, 2e12)
    nonce = factory.Sequence(lambda n: n)
    index = factory.Faker("uint256")
    value = factory.fuzzy.FuzzyInteger(1e15, 1e21)

    class Meta:
        model = Transaction


class TransactionLogFactory(factory.django.DjangoModelFactory):
    transaction = factory.SubFactory(TransactionFactory)
    index = factory.Sequence(lambda n: n)
    topics = ["0x0", "0x0", "0x0"]
    data = "0x0"

    class Meta:
        model = TransactionLog


class Web3ProviderFactory(factory.django.DjangoModelFactory):
    chain = factory.SubFactory(ChainFactory)
    url = factory.Sequence(lambda n: f"https://web3-{n:02}.example.com")
    connected = True
    enabled = True
    synced = False

    class Meta:
        model = Web3Provider


class SyncedWeb3ProviderFactory(Web3ProviderFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    synced = True
