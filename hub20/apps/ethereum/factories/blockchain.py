from typing import List

import factory
import factory.fuzzy
from django.utils import timezone

from ..models import Block, Chain, Transaction, TransactionDataRecord, TransferEvent

TEST_CHAIN_ID = 2


def find_parent_by_block_number(block):
    return Block.objects.filter(chain=block.chain, number=block.number - 1).first()


def make_parent_hash(block):
    parent = find_parent_by_block_number(block)
    return parent and parent.hash or block.default_parent_hash


class ChainFactory(factory.django.DjangoModelFactory):
    id = TEST_CHAIN_ID
    highest_block = 0
    native_token = factory.RelatedFactory(
        "hub20.apps.ethereum.factories.EtherFactory", factory_related_name="chain"
    )

    @factory.post_generation
    def blocks(obj, create, extracted, **kw):
        if not create:
            return

        if not extracted:
            BlockFactory(number=obj.highest_block, chain=obj)
        else:
            for block in extracted:
                obj.blocks.add(block)

    class Meta:
        model = Chain
        django_get_or_create = ("id",)


class SyncedChainFactory(ChainFactory):
    highest_block = 0


class BlockFactory(factory.django.DjangoModelFactory):
    chain = factory.SubFactory(SyncedChainFactory)
    hash = factory.Faker("hex64")
    number = factory.Sequence(lambda n: n)
    timestamp = factory.LazyAttribute(lambda obj: timezone.now())
    parent_hash = factory.LazyAttribute(lambda obj: make_parent_hash(obj))
    uncle_hashes: List = []

    class Params:
        default_parent_hash = factory.Faker("hex64")

    class Meta:
        model = Block


class TransactionDataFactory(factory.django.DjangoModelFactory):
    hash = factory.Faker("hex64")
    chain = factory.SubFactory(SyncedChainFactory)
    from_address = factory.Faker("ethereum_address")
    to_address = factory.Faker("ethereum_address")

    data = factory.LazyAttribute(
        lambda obj: {
            "from": obj.from_address,
            "to": obj.to_address,
            "chainId": hex(obj.chain.id),
            "gasUsed": obj.gas_used,
            "gasPrice": obj.gas_price,
            "blockNumber": obj.block_number,
            "blockHash": obj.block_hash,
            "value": obj.value,
            "nonce": obj.nonce,
        }
    )

    class Meta:
        model = TransactionDataRecord
        django_get_or_create = ("chain",)

    class Params:
        value = 0
        nonce = factory.Sequence(lambda n: n)
        status = 1
        gas_used = 21000
        gas_price = factory.fuzzy.FuzzyInteger(1e9, 100e9)
        block_number = None
        block_hash = None


class TransactionFactory(factory.django.DjangoModelFactory):
    block = factory.SubFactory(BlockFactory)
    hash = factory.Faker("hex64")
    from_address = factory.Faker("ethereum_address")
    to_address = factory.Faker("ethereum_address")

    receipt = factory.LazyAttribute(
        lambda obj: {
            "from": obj.from_address,
            "to": obj.to_address,
            "status": obj.status,
            "blockNumber": obj.block.number,
            "blockHash": obj.block.hash,
            "gasUsed": obj.gas_used,
            "effectiveGasPrice": obj.gas_price,
        }
    )

    class Meta:
        model = Transaction

    class Params:
        status = 1
        gas_used = factory.fuzzy.FuzzyInteger(21000, 200000)
        gas_price = factory.fuzzy.FuzzyInteger(1e9, 100e9)


class TransferEventFactory(factory.django.DjangoModelFactory):
    transaction = factory.SubFactory(TransactionFactory)
    sender = factory.Faker("ethereum_address")
    recipient = factory.Faker("ethereum_address")

    class Meta:
        model = TransferEvent


__all__ = [
    "TEST_CHAIN_ID",
    "ChainFactory",
    "SyncedChainFactory",
    "BlockFactory",
    "TransactionDataFactory",
    "TransactionFactory",
    "TransferEventFactory",
]
