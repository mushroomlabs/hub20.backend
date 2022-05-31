import datetime
import json
import logging
import uuid

from django.contrib.postgres.fields import ArrayField, HStoreField
from django.db import models
from django.db.models import Max
from django.utils import timezone
from model_utils.managers import QueryManager
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.types import BlockData, TxData, TxReceipt

from hub20.apps.core.fields import EthereumAddressField, HexField
from hub20.apps.core.models import TokenValueModel

logger = logging.getLogger(__name__)


def serialize_web3_data(data: AttributeDict):
    return json.loads(Web3.toJSON(data))


class Chain(models.Model):
    id = models.PositiveBigIntegerField(primary_key=True)
    name = models.CharField(max_length=128, default="EVM-compatible network")
    highest_block = models.PositiveIntegerField()
    objects = models.Manager()
    active = QueryManager(blockchainpaymentnetwork__providers__is_active=True)

    @property
    def provider(self):
        return self.blockchainpaymentnetwork.providers.filter(is_active=True).first()

    @property
    def synced(self):
        return self.provider and self.provider.synced and self.provider.is_active

    @property
    def short_name(self):
        return self.info.short_name

    @property
    def is_testnet(self):
        return self.info.testing_for is not None

    @property
    def is_rollup(self):
        return self.info.rollup_for is not None

    @property
    def is_sidechain(self):
        return self.info.sidechain_for is not None

    @property
    def is_scaling_network(self):
        return self.is_rollup or self.is_sidechain

    def __str__(self):
        return f"{self.name} ({self.id})"

    class Meta:
        ordering = ("id",)


class Block(models.Model):
    hash = HexField(max_length=64, primary_key=True)
    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="blocks")
    number = models.PositiveIntegerField(db_index=True)
    base_fee_per_gas = models.PositiveBigIntegerField(null=True)
    timestamp = models.DateTimeField()
    parent_hash = HexField(max_length=64)
    uncle_hashes = ArrayField(HexField(max_length=64))

    def __str__(self) -> str:
        return f"{self.hash} #{self.number}"

    @property
    def parent(self):
        return self.__class__.objects.filter(hash=self.parent_hash).first()

    @property
    def uncles(self):
        return self.__class__.objects.filter(hash__in=self.uncle_hashes)

    @property
    def confirmations(self) -> int:
        return self.chain.highest_block - self.number

    @classmethod
    def make(cls, block_data, chain_id: int):
        block_time = datetime.datetime.fromtimestamp(block_data.timestamp)
        block, _ = cls.objects.update_or_create(
            chain_id=chain_id,
            hash=block_data.hash,
            defaults={
                "number": block_data.number,
                "timestamp": timezone.make_aware(block_time),
                "parent_hash": block_data.parentHash,
                "uncle_hashes": block_data.uncles,
                "base_fee_per_gas": getattr(block_data, "baseFeePerGas", None),
            },
        )
        return block

    @classmethod
    def get_latest_block_number(cls, qs):
        return qs.aggregate(latest=Max("number")).get("latest") or 0

    class Meta:
        unique_together = ("chain", "hash", "number")


class AbstractTransactionRecord(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    hash = HexField(max_length=64, db_index=True)
    from_address = EthereumAddressField(db_index=True)
    to_address = EthereumAddressField(db_index=True)

    def __str__(self) -> str:
        return f"{self.__class__.__name__} {self.hash}"

    class Meta:
        abstract = True


class TransactionDataRecord(AbstractTransactionRecord):
    """
    Transaction data records do not represent transactions by themselves
    """

    chain = models.ForeignKey(Chain, related_name="transaction_data", on_delete=models.CASCADE)
    data = HStoreField()

    @classmethod
    def make(cls, chain_id: int, tx_data: TxData, force=False):
        action = cls.objects.update_or_create if force else cls.objects.get_or_create
        data, _ = action(
            chain_id=chain_id,
            hash=tx_data.hash,
            defaults={
                "from_address": tx_data["from"],
                "to_address": tx_data.to,
                "data": serialize_web3_data(tx_data),
            },
        )
        return data

    class Meta:
        unique_together = ("hash", "chain")


class Transaction(AbstractTransactionRecord):
    """
    Transaction models record the receipt, and should store
    all information related to a mined transaction
    """

    block = models.ForeignKey(Block, related_name="transactions", on_delete=models.CASCADE)
    receipt = HStoreField()

    def __str__(self) -> str:
        return f"Tx {self.hash}"

    @property
    def gas_used(self) -> int:
        return int(self.receipt.get("gasUsed", 0))

    @property
    def gas_price(self) -> int:
        return int(self.receipt.get("effectiveGasPrice", 0))

    @property
    def gas_fee(self) -> int:
        return self.gas_used * self.gas_price

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["hash", "block"], name="unique_tx_per_block"),
        ]

    @classmethod
    def make(
        cls,
        chain_id: int,
        tx_receipt: TxReceipt,
        block_data: BlockData,
        force=False,
    ):
        block = Block.make(chain_id=chain_id, block_data=block_data)
        action = cls.objects.update_or_create if force else cls.objects.get_or_create
        tx, _ = action(
            block=block,
            hash=tx_receipt.transactionHash,
            defaults={
                "from_address": tx_receipt["from"],
                "to_address": tx_receipt.to,
                "receipt": serialize_web3_data(tx_receipt),
            },
        )
        return tx


class EventIndexer(models.Model):
    chain = models.ForeignKey(Chain, related_name="indexers", on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    last_block = models.PositiveBigIntegerField(default=1)

    @classmethod
    def make(cls, chain_id: int, name: str):
        indexer, _ = cls.objects.get_or_create(chain_id=chain_id, name=name)
        return indexer

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["chain", "name"], name="unique_name_per_chain"),
        ]


class TransferEvent(TokenValueModel):
    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="transfers"
    )
    sender = EthereumAddressField()
    recipient = EthereumAddressField()
    log_index = models.SmallIntegerField(null=True)

    class Meta:
        unique_together = ("transaction", "log_index")
        ordering = ("transaction", "log_index")


__all__ = [
    "Chain",
    "Block",
    "Transaction",
    "TransactionDataRecord",
    "EventIndexer",
    "TransferEvent",
    "serialize_web3_data",
]
