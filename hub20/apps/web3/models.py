import logging
from typing import Optional
from urllib.parse import urlparse

from django.contrib.postgres.fields.ranges import IntegerRangeField
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Upper
from django.db.transaction import atomic
from model_utils.managers import QueryManager

from hub20.apps.core import get_wallet_model
from hub20.apps.core.exceptions import RoutingError
from hub20.apps.core.fields import AddressField
from hub20.apps.core.models import (
    BaseEthereumAccount,
    BaseProvider,
    BaseToken,
    Payment,
    PaymentRoute,
    PaymentRouteQuerySet,
    Token,
    TokenAmount,
    TokenValueModel,
    Transaction,
    TransactionDataRecord,
    TransferConfirmation,
    TransferError,
    TransferReceipt,
    Withdrawal,
)

from .app_settings import BLOCK_SCAN_RANGE, PAYMENT_ROUTE_LIFETIME
from .fields import Web3ProviderURLField

Wallet = get_wallet_model()
logger = logging.getLogger(__name__)


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
    from_address = AddressField(db_index=True)
    to_address = AddressField(db_index=True)

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


class NativeToken(BaseToken):
    NULL_ADDRESS = "0x0000000000000000000000000000000000000000"
    chain = models.OneToOneField(Chain, on_delete=models.CASCADE, related_name="native_token")


class Erc20Token(BaseToken):

    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="tokens")
    address = AddressField()

    objects = models.Manager()
    tradeable = QueryManager(Q(chain__providers__is_active=True) & Q(is_listed=True))
    listed = QueryManager(is_listed=True)

    @property
    def wrapped_by(self):
        return self.__class__.objects.filter(id__in=self.wrapping_tokens.values("wrapper"))

    @property
    def wraps(self):
        wrapping = getattr(self, "wrappedtoken", None)
        return wrapping and wrapping.wrapper

    @property
    def is_stable(self):
        return hasattr(self, "stable_pair")

    @property
    def tracks_currency(self):
        pairing = getattr(self, "stable_pair", None)
        return pairing and pairing.currency

    def __str__(self) -> str:
        components = [self.symbol]
        if self.is_ERC20:
            components.append(self.address)

        components.append(str(self.chain_id))
        return " - ".join(components)

    def from_wei(self, wei_amount: Wei) -> TokenAmount:
        value = TokenAmount(wei_amount) / (10**self.decimals)
        return TokenAmount(amount=value, currency=self)

    @classmethod
    def make(cls, address: str, chain: Chain, **defaults):
        obj, _ = cls.objects.update_or_create(address=address, chain=chain, defaults=defaults)
        return obj

    class Meta:
        unique_together = (("chain", "address"),)


class TokenList(AbstractTokenListModel):
    """
    A model to manage [token lists](https://tokenlists.org). Only
    admins can manage/import/export them.
    """

    url = TokenlistStandardURLField()
    version = models.CharField(max_length=32)

    class Meta:
        unique_together = ("url", "version")

    @classmethod
    def make(cls, url, token_list_data: TokenListDataModel, description=None):

        token_list, _ = cls.objects.get_or_create(
            url=url,
            version=token_list_data.version.as_string,
            defaults=dict(name=token_list_data.name),
        )
        token_list.description = description
        token_list.keywords.add(*token_list_data.keywords)
        token_list.save()

        for token_entry in token_list_data.tokens:
            token, _ = Token.objects.get_or_create(
                chain_id=token_entry.chainId,
                address=token_entry.address,
                defaults=dict(
                    name=token_entry.name,
                    decimals=token_entry.decimals,
                    symbol=token_entry.symbol,
                    logoURI=token_entry.logoURI,
                ),
            )
            token_list.tokens.add(token)
        return token_list


class Web3Provider(BaseProvider):
    chain = models.ForeignKey(Chain, related_name="providers", on_delete=models.CASCADE)
    url = Web3ProviderURLField()
    client_version = models.CharField(max_length=300, null=True)
    requires_geth_poa_middleware = models.BooleanField(default=False)
    supports_pending_filters = models.BooleanField(default=False)
    supports_eip1559 = models.BooleanField(default=False)
    max_block_scan_range = models.PositiveIntegerField(default=BLOCK_SCAN_RANGE)

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
    sender = AddressField()
    recipient = AddressField()
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
        BaseEthereumAccount, on_delete=models.CASCADE, related_name="blockchain_routes"
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
        return (current, current + PAYMENT_ROUTE_LIFETIME)

    @classmethod
    def is_usable_for_token(cls, token: Token):
        return token.is_listed and token.chain in Chain.active.all()

    @classmethod
    def make(cls, deposit):
        chain = deposit.currency.chain
        chain.refresh_from_db()
        if chain.synced:
            payment_window = cls.calculate_payment_window(chain)

            busy_routes = cls.objects.open().filter(deposit__currency=deposit.currency)
            available_accounts = BaseEthereumAccount.objects.exclude(
                blockchain_routes__in=busy_routes
            )

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
    def _execute(self):
        try:
            from hub20.apps.web3.client.web3 import Web3Client

            web3_client = Web3Client.select_for_transfer(amount=self.amount, address=self.address)
            tx_data = web3_client.transfer(amount=self.as_token_amount, address=self.address)
            BlockchainWithdrawalReceipt.objects.create(transfer=self, transaction_data=tx_data)
        except Exception as exc:
            raise TransferError(str(exc)) from exc

    class Meta:
        proxy = True


class BlockchainWithdrawalConfirmation(TransferConfirmation):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE)

    @property
    def fee(self) -> TokenAmount:
        native_token = Token.make_native(chain=self.transaction.block.chain)
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
]
