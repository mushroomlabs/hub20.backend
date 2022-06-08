import logging
import time
from typing import Optional

from django.contrib.postgres.fields.ranges import IntegerRangeField
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Upper

from hub20.apps.core.exceptions import RoutingError
from hub20.apps.core.models import Payment, PaymentRoute, PaymentRouteQuerySet
from hub20.apps.core.settings import app_settings

from .. import get_wallet_model
from ..signals import incoming_transfer_broadcast
from .accounts import BaseWallet
from .blockchain import Block, Chain, Transaction, TransactionDataRecord
from .networks import BlockchainPaymentNetwork
from .tokens import Erc20Token

logger = logging.getLogger(__name__)


class BlockchainRouteQuerySet(PaymentRouteQuerySet):
    def in_chain(self, chain_id) -> models.QuerySet:
        return self.filter(network__blockchainpaymentnetwork__chain_id=chain_id)

    def with_expiration(self) -> models.QuerySet:
        return self.annotate(
            start_block=Lower("payment_window"), expiration_block=Upper("payment_window")
        )

    def expired(self, block_number: Optional[int] = None) -> models.QuerySet:
        highest_block = F("network__blockchainpaymentnetwork__chain__highest_block")
        at_block = block_number if block_number is not None else highest_block
        return self.filter(expiration_block__lt=at_block)

    def available(self, block_number: Optional[int] = None) -> models.QuerySet:
        highest_block = F("network__blockchainpaymentnetwork__chain__highest_block")
        qs = self.with_expiration()
        at_block = block_number if block_number is not None else highest_block

        return qs.filter(start_block__lte=at_block, expiration_block__gte=at_block)

    def open(self, block_number: Optional[int] = None) -> models.QuerySet:
        highest_block = F("network__blockchainpaymentnetwork__chain__highest_block")
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
    NETWORK = BlockchainPaymentNetwork

    account = models.ForeignKey(
        BaseWallet, on_delete=models.CASCADE, related_name="blockchain_routes"
    )
    payment_window = IntegerRangeField()
    objects = BlockchainRouteQuerySet.as_manager()

    @property
    def chain(self):
        return self.network.blockchainpaymentnetwork.chain

    @property
    def start_block_number(self):
        return self.payment_window.lower

    @property
    def expiration_block_number(self):
        return self.payment_window.upper

    @property
    def is_expired(self):
        return self.chain.highest_block > self.expiration_block_number

    @property
    def description(self):
        return f"Blockchain Route {self.id} ('{self.identifier}' on blocks {self.payment_window})"

    def _process_native_token(self):
        while self.is_open:
            current_block = self.provider.w3.eth.block_number
            if not (self.start_block_number < current_block <= self.expiration_block_number):
                logger.warning(
                    f"{self.chain.name} is at block {current_block}, outside of payment window"
                )
                return

            self.chain.refresh_from_db()
            processed_blocks = Block.objects.filter(
                chain=self.chain, number__range=(self.start_block_number, current_block)
            ).values_list("number", flat=True)

            for block_number in range(self.start_block_number, current_block):
                if block_number not in processed_blocks:
                    logger.info(f"{self.description} checking #{block_number} on {self.chain}")
                    block_data = self.provider.w3.eth.get_block(
                        block_number, full_transactions=True
                    )
                    self.provider.extract_native_token_transfers(block_data)
                    Block.make(block_data, chain_id=self.chain.id)

            time.sleep(1)

    def _process_erc20_token(self):
        erc20_filter = self.provider.get_erc20_token_transfer_filter(
            token=self.deposit.currency.subclassed,
            start_block=self.start_block_number,
            end_block=self.expiration_block_number,
        )
        token: Erc20Token = self.currency.subclassed

        if self.provider.supports_pending_filters:
            erc20_pending_filter = self.provider.get_erc20_token_transfer(
                token=self.deposit.currency.subclassed, start_block="pending", end_block="pending"
            )
        while self.is_open:
            for event_data in erc20_filter.get_new_entries():
                self.provider._extract_transfer_event_from_erc20_token_transfer(
                    self.account, event_data
                )

            if self.provider.supports_pending_filters:
                for event_data in erc20_pending_filter.get_new_entries():
                    if event_data.args._to == self.account.address:
                        amount = token.from_wei(event_data.args._value)
                        incoming_transfer_broadcast.send(
                            account=self.account,
                            amount=amount,
                            transaction_data=event_data,
                            sender=TransactionDataRecord,
                        )

            time.sleep(1)

    def process(self):
        if self.deposit.currency.subclassed.is_ERC20:
            self._process_erc20_token()
        else:
            self._process_native_token()

    @staticmethod
    def calculate_payment_window(chain: Chain):
        current = chain.highest_block
        return (current, current + app_settings.Blockchain.payment_route_lifetime)

    @classmethod
    def make(cls, deposit):
        chain = deposit.currency.subclassed.chain
        chain.refresh_from_db()
        if chain.provider and chain.provider.synced:
            payment_window = cls.calculate_payment_window(chain=chain)

            busy_routes = cls.objects.open().filter(deposit__currency=deposit.currency)
            available_accounts = BaseWallet.objects.exclude(blockchain_routes__in=busy_routes)

            account = available_accounts.order_by("?").first()
            if not account:
                Wallet = get_wallet_model()
                account = Wallet.generate()

            return cls.objects.create(
                network=chain.blockchainpaymentnetwork,
                account=account,
                deposit=deposit,
                payment_window=payment_window,
            )
        else:
            raise RoutingError("Failed to create blockchain route. Chain data not synced")


class BlockchainPayment(Payment):
    transaction = models.OneToOneField(Transaction, unique=True, on_delete=models.CASCADE)

    @property
    def identifier(self):
        return str(self.transaction.hash)


__all__ = ["BlockchainPaymentRoute", "BlockchainPayment"]
