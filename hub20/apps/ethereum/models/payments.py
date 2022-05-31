import logging
from typing import Optional

from django.contrib.postgres.fields.ranges import IntegerRangeField
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Upper

from hub20.apps.core.exceptions import RoutingError
from hub20.apps.core.models import BaseToken, Payment, PaymentRoute, PaymentRouteQuerySet
from hub20.apps.core.settings import app_settings

from .. import get_wallet_model
from .accounts import BaseWallet
from .blockchain import Chain, Transaction
from .networks import BlockchainPaymentNetwork

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
        chain = deposit.currency.subclassed.chain

        chain.refresh_from_db()
        if chain.synced:
            payment_window = cls.calculate_payment_window(chain)

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
