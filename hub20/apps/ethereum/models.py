import datetime
import functools
import json
import logging
import os
from typing import Optional
from urllib.parse import urlparse

import ethereum
from django.contrib.postgres.fields import ArrayField, HStoreField
from django.contrib.postgres.fields.ranges import IntegerRangeField
from django.db import models
from django.db.models import F, Max, Q
from django.db.models.functions import Lower, Upper
from django.db.transaction import atomic
from django.utils import timezone
from hdwallet import HDWallet
from hdwallet.symbols import ETH
from model_utils.managers import InheritanceManager, QueryManager
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.types import BlockData, TxData, TxReceipt

from hub20.apps.core.exceptions import RoutingError
from hub20.apps.core.fields import EthereumAddressField, HexField
from hub20.apps.core.models import (
    BaseToken,
    Payment,
    PaymentNetworkProvider,
    PaymentRoute,
    PaymentRouteQuerySet,
    TokenAmount,
    TokenValueModel,
    TransferConfirmation,
    TransferError,
    TransferReceipt,
    Withdrawal,
)
from hub20.apps.core.settings import app_settings

from .constants import NULL_ADDRESS
from .fields import Web3ProviderURLField

logger = logging.getLogger(__name__)


def serialize_web3_data(data: AttributeDict):
    return json.loads(Web3.toJSON(data))


class Chain(models.Model):
    id = models.PositiveBigIntegerField(primary_key=True)
    name = models.CharField(max_length=128, default="EVM-compatible network")
    highest_block = models.PositiveIntegerField()
    objects = models.Manager()
    active = QueryManager(providers__is_active=True)

    @property
    def provider(self):
        return self.providers.filter(is_active=True).first()

    @property
    def synced(self):
        return self.provider.synced and self.provider.is_active

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


class ChainMetadata(models.Model):
    chain = models.OneToOneField(Chain, related_name="info", on_delete=models.CASCADE)
    short_name = models.SlugField(null=True)
    testing_for = models.ForeignKey(
        Chain, null=True, blank=True, related_name="testnets", on_delete=models.CASCADE
    )
    rollup_for = models.ForeignKey(
        Chain, null=True, blank=True, related_name="rollups", on_delete=models.CASCADE
    )
    sidechain_for = models.ForeignKey(
        Chain, null=True, blank=True, related_name="sidechains", on_delete=models.CASCADE
    )


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


class BaseWallet(models.Model):
    address = EthereumAddressField(unique=True, db_index=True, blank=False)
    transactions = models.ManyToManyField(Transaction)
    objects = InheritanceManager()

    def historical_balance(self, token):
        return self.balance_records.filter(currency=token).order_by("block__number")

    def current_balance(self, token):
        return self.historical_balance(token).last()

    @property
    def balances(self):
        # There has to be a better way to convert a ValuesQuerySet
        # into a Queryset, but for the moment it will be okay.
        record_qs = self.balance_records.values("currency").annotate(
            block__number=Max("block__number")
        )

        filter_q = functools.reduce(lambda x, y: x | y, [Q(**r) for r in record_qs])

        return self.balance_records.filter(amount__gt=0).filter(filter_q)

    @property
    def private_key_bytes(self) -> Optional[bytes]:
        private_key = getattr(self, "private_key", None)
        return private_key and bytearray.fromhex(private_key[2:])

    def __str__(self):
        return self.address


class WalletBalanceRecord(TokenValueModel):
    """
    Provides a blocktime-series record of balances for any account
    """

    wallet = models.ForeignKey(
        BaseWallet, related_name="balance_records", on_delete=models.CASCADE
    )
    block = models.ForeignKey(Block, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("wallet", "currency", "block")


class ColdWallet(BaseWallet):
    @classmethod
    def generate(cls):
        raise TypeError("Cold wallets do not store private keys and can not be generated")


class KeystoreAccount(BaseWallet):
    private_key = HexField(max_length=64, unique=True)

    @classmethod
    def generate(cls):
        private_key = os.urandom(32)
        address = ethereum.utils.privtoaddr(private_key)
        checksum_address = ethereum.utils.checksum_encode(address.hex())
        return cls.objects.create(address=checksum_address, private_key=private_key.hex())


class HierarchicalDeterministicWallet(BaseWallet):
    BASE_PATH_FORMAT = "m/44'/60'/0'/0/{index}"

    index = models.PositiveIntegerField(unique=True)

    @property
    def private_key(self):
        wallet = self.__class__.get_wallet(index=self.index)
        return wallet.private_key()

    @property
    def private_key_bytes(self) -> bytes:
        return bytearray.fromhex(self.private_key)

    @classmethod
    def get_wallet(cls, index: int) -> HDWallet:
        wallet = HDWallet(symbol=ETH)

        if app_settings.Wallet.mnemonic:
            wallet.from_mnemonic(mnemonic=app_settings.Wallet.mnemonic)
        elif app_settings.Wallet.root_key:
            wallet.from_xprivate_key(xprivate_key=app_settings.Wallet.root_key)
        else:
            raise ValueError("Can not generate new addresses for HD Wallets. No seed available")

        wallet.from_path(cls.BASE_PATH_FORMAT.format(index=index))
        return wallet

    @classmethod
    def generate(cls):
        latest_generation = cls.get_latest_generation()
        index = 0 if latest_generation is None else latest_generation + 1
        wallet = HierarchicalDeterministicWallet.get_wallet(index)
        return cls.objects.create(index=index, address=wallet.p2pkh_address())

    @classmethod
    def get_latest_generation(cls) -> Optional[int]:
        return cls.objects.aggregate(generation=Max("index")).get("generation")


# Tokens
class NativeToken(BaseToken):
    chain = models.OneToOneField(Chain, on_delete=models.CASCADE, related_name="native_token")

    @property
    def address(self):
        return NULL_ADDRESS


class Erc20Token(BaseToken):

    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="tokens")
    address = EthereumAddressField()

    objects = models.Manager()
    tradeable = QueryManager(Q(chain__providers__is_active=True) & Q(is_listed=True))
    listed = QueryManager(is_listed=True)

    def __str__(self) -> str:
        components = [self.symbol]
        if self.is_ERC20:
            components.append(self.address)

        components.append(str(self.chain_id))
        return " - ".join(components)

    @classmethod
    def make(cls, address: str, chain: Chain, **defaults):
        obj, _ = cls.objects.update_or_create(address=address, chain=chain, defaults=defaults)
        return obj

    class Meta:
        unique_together = (("chain", "address"),)


class Web3Provider(PaymentNetworkProvider):
    chain = models.ForeignKey(Chain, related_name="providers", on_delete=models.CASCADE)
    url = Web3ProviderURLField()
    client_version = models.CharField(max_length=300, null=True)
    requires_geth_poa_middleware = models.BooleanField(default=False)
    supports_pending_filters = models.BooleanField(default=False)
    supports_eip1559 = models.BooleanField(default=False)
    max_block_scan_range = models.PositiveIntegerField(default=app_settings.Blockchain.scan_range)

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


# Payments
class BlockchainRouteQuerySet(PaymentRouteQuerySet):
    def in_chain(self, chain_id) -> models.QuerySet:
        return self.filter(deposit__currency__chain__id=chain_id)

    def with_provider(self) -> models.QuerySet:
        return self.filter(deposit__currency__chain__providers__is_active=True)

    def with_expiration(self) -> models.QuerySet:
        return self.annotate(
            start_block=Lower("payment_window"), expiration_block=Upper("payment_window")
        )

    def expired(self, block_number: Optional[int] = None) -> models.QuerySet:
        highest_block = F("deposit__currency__chain__highest_block")
        at_block = block_number if block_number is not None else highest_block
        return self.filter(expiration_block__lt=at_block)

    def available(self, block_number: Optional[int] = None) -> models.QuerySet:
        highest_block = F("deposit__currency__chain__highest_block")
        qs = self.with_expiration()
        at_block = block_number if block_number is not None else highest_block

        return qs.filter(start_block__lte=at_block, expiration_block__gte=at_block)

    def open(self, block_number: Optional[int] = None) -> models.QuerySet:
        highest_block = F("deposit__currency__chain__highest_block")
        at_block = block_number if block_number is not None else highest_block

        no_defined_amount = Q(deposit__paymentorder__isnull=True)

        confirmed = Q(total_confirmed__gte=F("deposit__paymentorder__amount")) & Q(
            currency=F("deposit__currency")
        )
        expired = Q(expiration_block__lt=at_block)

        return (
            self.with_expiration()
            .exclude(expired)
            .with_payment_amounts()
            .filter(no_defined_amount | ~confirmed)
        )


class BlockchainPaymentRoute(PaymentRoute):
    NETWORK = "blockchain"

    account = models.ForeignKey(
        BaseWallet, on_delete=models.CASCADE, related_name="blockchain_routes"
    )
    payment_window = IntegerRangeField()
    objects = BlockchainRouteQuerySet.as_manager()

    @property
    def chain(self):
        return self.deposit.currency.chain

    @property
    def start_block_number(self):
        return self.payment_window.lower

    @property
    def expiration_block_number(self):
        return self.payment_window.upper

    @property
    def is_expired(self):
        return self.chain.highest_block > self.expiration_block_number

    @staticmethod
    def calculate_payment_window(chain):
        if not chain.synced:
            raise ValueError("Chain is not synced")

        current = chain.highest_block
        return (current, current + app_settings.Blockchain.payment_route_lifetime)

    @classmethod
    def is_usable_for_token(cls, token: BaseToken):
        return token.is_listed and token.chain in Chain.active.all()

    @classmethod
    def make(cls, deposit):
        chain = deposit.currency.chain
        chain.refresh_from_db()
        if chain.synced:
            payment_window = cls.calculate_payment_window(chain)

            busy_routes = cls.objects.open().filter(deposit__currency=deposit.currency)
            available_accounts = BaseWallet.objects.exclude(blockchain_routes__in=busy_routes)

            account = available_accounts.order_by("?").first() or Wallet.generate()

            return cls.objects.create(
                account=account, deposit=deposit, payment_window=payment_window
            )
        else:
            raise RoutingError("Failed to create blockchain route. Chain data not synced")


class BlockchainPayment(Payment):
    transaction = models.OneToOneField(Transaction, unique=True, on_delete=models.CASCADE)

    @property
    def identifier(self):
        return str(self.transaction.hash)


# Transfers
class BlockchainWithdrawalReceipt(TransferReceipt):
    transaction_data = models.OneToOneField(TransactionDataRecord, on_delete=models.CASCADE)


class BlockchainWithdrawal(Withdrawal):
    address = EthereumAddressField(db_index=True)

    def _execute(self):
        try:
            from hub20.apps.ethereum.client.web3 import Web3Client

            web3_client = Web3Client.select_for_transfer(amount=self.amount, address=self.address)
            tx_data = web3_client.transfer(amount=self.as_token_amount, address=self.address)
            BlockchainWithdrawalReceipt.objects.create(transfer=self, transaction_data=tx_data)
        except Exception as exc:
            raise TransferError(str(exc)) from exc


class BlockchainWithdrawalConfirmation(TransferConfirmation):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE)

    @property
    def fee(self) -> TokenAmount:
        native_token = self.transaction.block.chain.native_token
        return native_token.from_wei(self.transaction.gas_fee)


__all__ = [
    "Chain",
    "ChainMetadata",
    "Block",
    "EventIndexer",
    "Transaction",
    "TransactionDataRecord",
    "Web3Provider",
    "Explorer",
    "TransferEvent",
    "NativeToken",
    "Erc20Token",
    "BaseWallet",
    "ColdWallet",
    "KeystoreAccount",
    "HierarchicalDeterministicWallet",
    "WalletBalanceRecord",
]
