import datetime
import logging
from typing import Optional
from urllib.parse import urlparse

from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.db import models
from django.db.models import Max, Q
from django.utils import timezone
from hexbytes import HexBytes
from model_utils.managers import InheritanceManager, QueryManager
from web3.datastructures import AttributeDict

from .app_settings import START_BLOCK_NUMBER
from .fields import EthereumAddressField, HexField, Uint256Field
from .typing import Address

logger = logging.getLogger(__name__)


class TransactionQuerySet(models.QuerySet):
    def involving_address(self, chain, address):
        return self.filter(block__chain=chain).filter(
            Q(from_address=address)
            | Q(to_address=address)
            | Q(baseethereumaccount__address=address)
        )

    def last_block_with(self, chain, address):
        qs = self.involving_address(chain, address).select_related("block")
        return qs.aggregate(highest=Max("block__number")).get("highest") or 0


class Chain(models.Model):
    id = models.PositiveBigIntegerField(primary_key=True)
    name = models.CharField(max_length=128, default="EVM-compatible network")
    is_mainnet = models.BooleanField(default=True)
    highest_block = models.PositiveIntegerField()
    objects = models.Manager()
    active = QueryManager(provider__enabled=True)

    @property
    def gas_price_estimate_cache_key(self):
        return f"GAS_PRICE_ESTIMATE_{self.id}"

    @property
    def synced(self):
        return self.provider.synced and self.provider.enabled

    def _get_gas_price_estimate(self):
        return cache.get(self.gas_price_estimate_cache_key, None)

    def _set_gas_price_estimate(self, value):
        return cache.set(self.gas_price_estimate_cache_key, value)

    gas_price_estimate = property(_get_gas_price_estimate, _set_gas_price_estimate)


class Block(models.Model):
    hash = HexField(max_length=64, primary_key=True)
    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="blocks")
    number = models.PositiveIntegerField(db_index=True)
    timestamp = models.DateTimeField()
    parent_hash = HexField(max_length=64)
    uncle_hashes = ArrayField(HexField(max_length=64))

    def __str__(self) -> str:
        hash_hex = self.hash if type(self.hash) is str else self.hash.hex()
        return f"{hash_hex} #{self.number}"

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
            },
        )
        return block

    @classmethod
    def get_latest_block_number(cls, qs):
        return qs.aggregate(latest=Max("number")).get("latest") or START_BLOCK_NUMBER

    class Meta:
        unique_together = ("chain", "hash", "number")


class Transaction(models.Model):
    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="transactions")
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="transactions")
    hash = HexField(max_length=64, db_index=True)
    from_address = EthereumAddressField(db_index=True)
    to_address = EthereumAddressField(db_index=True)
    gas_used = Uint256Field()
    gas_price = Uint256Field()
    nonce = Uint256Field()
    index = Uint256Field()
    value = Uint256Field()
    data = models.TextField()
    success = models.BooleanField(null=True)

    objects = TransactionQuerySet.as_manager()

    @property
    def hash_hex(self):
        return self.hash if type(self.hash) is str else self.hash.hex()

    @property
    def gas_fee(self) -> Uint256Field:
        return self.gas_used * self.gas_price

    def __str__(self) -> str:
        return f"Tx {self.hash_hex}"

    @classmethod
    def make(
        cls,
        chain_id,
        block_data: AttributeDict,
        tx_data: AttributeDict,
        tx_receipt: AttributeDict,
        force=False,
    ):
        tx = cls.objects.filter(chain_id=chain_id, hash=tx_receipt.transactionHash).first()

        if tx and not force:
            return tx

        try:
            assert tx_data.blockHash == tx_receipt.blockHash, "tx data/receipt block hash mismatch"
            assert tx_data.blockHash == HexBytes(block_data.hash), "Block hash mismatch"
            assert tx_data.hash == tx_receipt.transactionHash, "Tx hash mismatch"
            assert tx_data["from"] == tx_receipt["from"], "Sender address mismatch"
            assert tx_data["to"] == tx_receipt["to"], "Recipient address mismatch"
            assert tx_data.transactionIndex == tx_receipt.transactionIndex, "Tx index mismatch"
        except AssertionError as exc:
            logger.warning(f"Transaction will not be recorded: {exc}")
            return None

        block = Block.make(block_data, chain_id=chain_id)

        tx, _ = cls.objects.get_or_create(
            hash=tx_receipt.transactionHash,
            block=block,
            chain=block.chain,
            defaults={
                "from_address": tx_receipt["from"],
                "to_address": tx_receipt.to,
                "index": tx_receipt.transactionIndex,
                "gas_used": tx_receipt.gasUsed,
                "gas_price": tx_data.gasPrice,
                "nonce": tx_data.nonce,
                "value": tx_data.value,
                "data": tx_data.input,
                "success": bool(tx_receipt.status),
            },
        )

        for log_data in tx_receipt.logs:
            TransactionLog.make(log_data, tx)

        return tx

    class Meta:
        unique_together = ("hash", "chain")


class TransactionLog(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="logs")
    index = models.SmallIntegerField()
    data = models.TextField()
    topics = ArrayField(models.TextField())

    @classmethod
    def make(cls, log_data, transaction: Transaction):
        tx_log, _ = cls.objects.get_or_create(
            index=log_data.logIndex,
            transaction=transaction,
            defaults={"data": log_data.data, "topics": [topic.hex() for topic in log_data.topics]},
        )
        return tx_log

    class Meta:
        unique_together = ("transaction", "index")


class AbstractTokenInfo(models.Model):
    name = models.CharField(max_length=500)
    symbol = models.CharField(max_length=16)
    decimals = models.PositiveIntegerField(default=18)

    class Meta:
        abstract = True


class NativeToken(AbstractTokenInfo):
    chain = models.OneToOneField(Chain, on_delete=models.CASCADE, related_name="native_token")


class BaseEthereumAccount(models.Model):
    address = EthereumAddressField(unique=True, db_index=True)
    transactions = models.ManyToManyField(Transaction)
    objects = InheritanceManager()

    def last_contract_interaction(
        self, chain: Chain, contract_address: Address
    ) -> Optional[Transaction]:
        q_contract_transaction = Q(from_address=contract_address) | Q(to_address=contract_address)
        return self.transactions.filter(q_contract_transaction).order_by("-block__number").first()

    def most_recent_contract_interaction(self, chain: Chain, contract_address: Address) -> int:
        transaction = self.last_contract_interaction(
            chain=chain, contract_address=contract_address
        )
        return transaction and transaction.block.number or 0

    def __str__(self):
        return self.address

    @property
    def private_key_bytes(self) -> Optional[bytes]:
        private_key = getattr(self, "private_key", None)
        return private_key and bytearray.fromhex(private_key[2:])


class Web3Provider(models.Model):
    url = models.URLField()
    chain = models.OneToOneField(Chain, related_name="provider", on_delete=models.CASCADE)
    enabled = models.BooleanField(default=True)
    synced = models.BooleanField(default=False)
    connected = models.BooleanField(default=False)

    objects = models.Manager()
    available = QueryManager(enabled=True, synced=True, connected=True)

    @property
    def is_online(self):
        return self.connected and self.synced

    @property
    def hostname(self):
        return urlparse(self.url).hostname


class Explorer(models.Model):
    chain = models.ForeignKey(Chain, related_name="explorers", on_delete=models.CASCADE)
    url = models.URLField()

    class Meta:
        unique_together = ("url", "chain")


__all__ = [
    "Block",
    "Chain",
    "Transaction",
    "TransactionLog",
    "BaseEthereumAccount",
    "AbstractTokenInfo",
    "NativeToken",
    "Web3Provider",
    "Explorer",
]
