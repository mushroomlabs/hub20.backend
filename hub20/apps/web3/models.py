import logging
from typing import Optional
from urllib.parse import urlparse

from django.contrib.postgres.fields.ranges import IntegerRangeField
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Upper
from django.db.transaction import atomic

from hub20.apps.core import get_wallet_model
from hub20.apps.core.exceptions import RoutingError
from hub20.apps.core.fields import AddressField
from hub20.apps.core.models import (
    BaseEthereumAccount,
    BaseProvider,
    Chain,
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
    "Web3Provider",
    "Explorer",
    "TransferEvent",
]
