import datetime
import json
import logging
from typing import Optional
from urllib.parse import urlparse

from django.contrib.postgres.fields import ArrayField, HStoreField
from django.db import models
from django.db.models import Max
from django.db.transaction import atomic
from django.utils import timezone
from model_utils.managers import InheritanceManager, QueryManager
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.types import BlockData, TxData, TxReceipt

from .app_settings import START_BLOCK_NUMBER
from .fields import EthereumAddressField, HexField, Web3ProviderURLField

logger = logging.getLogger(__name__)


def serialize_web3_data(data: AttributeDict):
    return json.loads(Web3.toJSON(data))


class Chain(models.Model):
    id = models.PositiveBigIntegerField(primary_key=True)
    name = models.CharField(max_length=128, default="EVM-compatible network")
    is_mainnet = models.BooleanField(default=True)
    highest_block = models.PositiveIntegerField()
    objects = models.Manager()
    active = QueryManager(providers__is_active=True)

    @property
    def provider(self):
        return self.providers.filter(is_active=True).first()

    @property
    def synced(self):
        return self.provider.synced and self.provider.is_active

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
        return qs.aggregate(latest=Max("number")).get("latest") or START_BLOCK_NUMBER

    class Meta:
        unique_together = ("chain", "hash", "number")


class AbstractTransactionRecord(models.Model):
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


class AbstractTokenInfo(models.Model):
    name = models.CharField(max_length=500)
    symbol = models.CharField(max_length=16)
    decimals = models.PositiveIntegerField(default=18)

    class Meta:
        abstract = True


class NativeToken(AbstractTokenInfo):
    chain = models.OneToOneField(Chain, on_delete=models.CASCADE, related_name="native_token")


class BaseEthereumAccount(models.Model):
    address = EthereumAddressField(unique=True, db_index=True, blank=False)
    transactions = models.ManyToManyField(Transaction)
    objects = InheritanceManager()

    def __str__(self):
        return self.address

    @property
    def private_key_bytes(self) -> Optional[bytes]:
        private_key = getattr(self, "private_key", None)
        return private_key and bytearray.fromhex(private_key[2:])


class Web3Provider(models.Model):
    chain = models.ForeignKey(Chain, related_name="providers", on_delete=models.CASCADE)
    url = Web3ProviderURLField()
    client_version = models.CharField(max_length=300, null=True)
    requires_geth_poa_middleware = models.BooleanField(default=False)
    supports_pending_filters = models.BooleanField(default=False)
    supports_eip1559 = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    synced = models.BooleanField(default=False)
    connected = models.BooleanField(default=False)

    objects = models.Manager()
    active = QueryManager(is_active=True)
    available = QueryManager(synced=True, connected=True, is_active=True)

    @property
    def is_online(self):
        return self.connected and self.synced

    @property
    def hostname(self):
        return urlparse(self.url).hostname

    @atomic()
    def activate(self):
        self.chain.providers.exclude(id=self.id).update(is_active=False)
        self.is_active = True
        self.save()

    def __str__(self):
        return self.hostname


class Explorer(models.Model):
    chain = models.ForeignKey(Chain, related_name="explorers", on_delete=models.CASCADE)
    name = models.CharField(max_length=200, null=True)
    url = models.URLField()
    standard = models.CharField(max_length=200, null=True)

    class Meta:
        unique_together = ("url", "chain")


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


__all__ = [
    "Block",
    "Chain",
    "Transaction",
    "TransactionDataRecord",
    "BaseEthereumAccount",
    "AbstractTokenInfo",
    "NativeToken",
    "Web3Provider",
    "Explorer",
    "EventIndexer",
]
