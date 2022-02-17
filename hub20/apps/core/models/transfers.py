from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.contrib.postgres.fields import HStoreField
from django.db import models
from model_utils.managers import InheritanceManager, InheritanceManagerMixin, QueryManagerMixin
from model_utils.models import TimeStampedModel

from hub20.apps.blockchain.fields import EthereumAddressField
from hub20.apps.blockchain.models import Transaction, TransactionDataRecord
from hub20.apps.core.choices import TRANSFER_STATUS, WITHDRAWAL_NETWORKS
from hub20.apps.ethereum_money.client import Web3Client
from hub20.apps.ethereum_money.models import (
    EthereumToken,
    EthereumTokenAmount,
    EthereumTokenValueModel,
)
from hub20.apps.raiden.client.node import RaidenClient
from hub20.apps.raiden.exceptions import RaidenPaymentError
from hub20.apps.raiden.models import Payment

logger = logging.getLogger(__name__)


class TransferError(Exception):
    pass


class TransferOperationError(Exception):
    pass


class TransferStatusQueryManager(InheritanceManagerMixin, QueryManagerMixin, models.Manager):
    def get_queryset(self):
        qs = InheritanceManagerMixin.get_queryset(self).filter(self._q)
        if self._order_by is not None:
            return qs.order_by(*self._order_by)
        return qs


class Transfer(TimeStampedModel, EthereumTokenValueModel):
    reference = models.UUIDField(default=uuid.uuid4, unique=True)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transfers_sent"
    )
    memo = models.TextField(null=True, blank=True)
    identifier = models.CharField(max_length=300, null=True, blank=True)
    execute_on = models.DateTimeField(auto_now_add=True)

    objects = InheritanceManager()
    processed = TransferStatusQueryManager(receipt__isnull=False)
    canceled = TransferStatusQueryManager(cancellation__isnull=False)
    failed = TransferStatusQueryManager(failure__isnull=False)
    confirmed = TransferStatusQueryManager(confirmation__isnull=False)
    pending = TransferStatusQueryManager(
        receipt__isnull=True,
        cancellation__isnull=True,
        failure__isnull=True,
        confirmation__isnull=True,
    )

    @property
    def status(self) -> str:
        if self.is_confirmed:
            return TRANSFER_STATUS.confirmed
        elif self.is_failed:
            return TRANSFER_STATUS.failed
        elif self.is_canceled:
            return TRANSFER_STATUS.canceled
        elif self.is_processed:
            return TRANSFER_STATUS.processed
        else:
            return TRANSFER_STATUS.scheduled

    @property
    def is_canceled(self):
        return TransferCancellation.objects.filter(transfer=self).exists()

    @property
    def is_confirmed(self):
        return TransferConfirmation.objects.filter(transfer=self).exists()

    @property
    def is_failed(self):
        return TransferFailure.objects.filter(transfer=self).exists()

    @property
    def is_processed(self) -> bool:
        return TransferReceipt.objects.filter(transfer=self).exists()

    @property
    def is_finalized(self) -> bool:
        return self.status != TRANSFER_STATUS.scheduled

    def execute(self):
        if self.is_finalized:
            logger.warning(f"{self} is already finalized as {self.status}")
            return

        try:
            # The user has already been deducted from the transfer amount upon
            # creation. This check here just enforces that the transfer is not
            # doing double spend of reserved funds.
            sender_balance = self.sender.account.get_balance_token_amount(token=self.currency)

            if sender_balance is None:
                raise TransferError("No balance available")

            if sender_balance.amount < 0:
                raise TransferError("Insufficient balance")

            self._execute()
        except TransferError as exc:
            logger.info(f"{self} failed: {str(exc)}")
            TransferFailure.objects.create(transfer=self)
        except Exception as exc:
            TransferFailure.objects.create(transfer=self)
            logger.exception(exc)

    def _execute(self):
        raise NotImplementedError()


class InternalTransfer(Transfer):
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="internal_transfers_received",
    )

    def _execute(self):
        TransferConfirmation.objects.create(transfer=self)


class Withdrawal(Transfer):
    address = EthereumAddressField(db_index=True)
    payment_network = models.CharField(max_length=64, choices=WITHDRAWAL_NETWORKS)


class BlockchainWithdrawal(Withdrawal):
    def _execute(self):
        try:
            assert self.payment_network == WITHDRAWAL_NETWORKS.blockchain, "Wrong payment network"
            web3_client = Web3Client.select_for_transfer(amount=self.amount, address=self.address)
            tx_data = web3_client.transfer(amount=self.as_token_amount, address=self.address)
            BlockchainWithdrawalReceipt.objects.create(transfer=self, transaction_data=tx_data)
        except Exception as exc:
            raise TransferError(str(exc)) from exc

    class Meta:
        proxy = True


class RaidenWithdrawal(Withdrawal):
    def _execute(self):
        try:
            assert self.payment_network == WITHDRAWAL_NETWORKS.raiden, "Wrong payment network"
            raiden_client = RaidenClient.select_for_transfer(
                amount=self.amount, address=self.address
            )
            payment_data = raiden_client.transfer(
                amount=self.as_token_amount,
                address=self.address,
                identifier=raiden_client._ensure_valid_identifier(self.identifier),
            )
            RaidenWithdrawalReceipt.objects.create(transfer=self, payment_data=payment_data)
        except AssertionError:
            raise TransferError("Incorrect transfer method")
        except RaidenPaymentError as exc:
            raise TransferError(exc.message) from exc

    class Meta:
        proxy = True


class TransferReceipt(TimeStampedModel):
    transfer = models.OneToOneField(Transfer, on_delete=models.CASCADE, related_name="receipt")


class BlockchainWithdrawalReceipt(TransferReceipt):
    transaction_data = models.OneToOneField(TransactionDataRecord, on_delete=models.CASCADE)


class RaidenWithdrawalReceipt(TransferReceipt):
    payment_data = HStoreField()


class TransferConfirmation(TimeStampedModel):
    transfer = models.OneToOneField(
        Transfer, on_delete=models.CASCADE, related_name="confirmation"
    )
    objects = InheritanceManager()


class BlockchainWithdrawalConfirmation(TransferConfirmation):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE)

    @property
    def fee(self) -> EthereumTokenAmount:
        native_token = EthereumToken.make_native(chain=self.transaction.block.chain)
        return native_token.from_wei(self.transaction.gas_fee)


class RaidenWithdrawalConfirmation(TransferConfirmation):
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE)


class TransferFailure(TimeStampedModel):
    transfer = models.OneToOneField(Transfer, on_delete=models.CASCADE, related_name="failure")


class TransferCancellation(TimeStampedModel):
    transfer = models.OneToOneField(
        Transfer, on_delete=models.CASCADE, related_name="cancellation"
    )
    canceled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


__all__ = [
    "Transfer",
    "TransferFailure",
    "TransferCancellation",
    "TransferConfirmation",
    "TransferReceipt",
    "TransferError",
    "BlockchainWithdrawal",
    "BlockchainWithdrawalReceipt",
    "RaidenWithdrawal",
    "RaidenWithdrawalReceipt",
    "InternalTransfer",
    "BlockchainWithdrawalConfirmation",
    "RaidenWithdrawalConfirmation",
    "Withdrawal",
]
