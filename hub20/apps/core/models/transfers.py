from __future__ import annotations

import logging
from typing import Union

from django.conf import settings
from django.db import models
from model_utils.managers import InheritanceManager, InheritanceManagerMixin, QueryManagerMixin
from model_utils.models import TimeStampedModel

from hub20.apps.core.choices import TRANSFER_STATUS
from hub20.apps.core.models.tokens import TokenValueModel

from ..exceptions import TransferError
from .base import BaseModel
from .networks import InternalPaymentNetwork, PaymentNetwork
from .providers import PaymentNetworkProvider_T

logger = logging.getLogger(__name__)


class TransferStatusQueryManager(InheritanceManagerMixin, QueryManagerMixin, models.Manager):
    def get_queryset(self):
        qs = InheritanceManagerMixin.get_queryset(self).filter(self._q)
        if self._order_by is not None:
            return qs.order_by(*self._order_by)
        return qs


class Transfer(BaseModel, TimeStampedModel, TokenValueModel):
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transfers_sent"
    )
    memo = models.TextField(null=True, blank=True)
    identifier = models.CharField(max_length=300, null=True, blank=True)
    network = models.ForeignKey(PaymentNetwork, on_delete=models.PROTECT, related_name="transfers")

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

    @property
    def provider(self) -> Union[PaymentNetworkProvider_T, None]:
        return self.network.providers(manager="available").select_subclasses().first()

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

    class Meta:
        ordering = ("created",)


class InternalTransfer(Transfer):
    NETWORK = InternalPaymentNetwork
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="internal_transfers_received",
    )

    def _execute(self):
        TransferConfirmation.objects.create(transfer=self)


class TransferReceipt(BaseModel, TimeStampedModel):
    transfer = models.OneToOneField(Transfer, on_delete=models.CASCADE, related_name="receipt")


class TransferConfirmation(BaseModel, TimeStampedModel):
    transfer = models.OneToOneField(
        Transfer, on_delete=models.CASCADE, related_name="confirmation"
    )
    objects = InheritanceManager()


class TransferFailure(BaseModel, TimeStampedModel):
    transfer = models.OneToOneField(Transfer, on_delete=models.CASCADE, related_name="failure")


class TransferCancellation(BaseModel, TimeStampedModel):
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
    "InternalTransfer",
]
