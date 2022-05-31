from __future__ import annotations

from django.contrib.postgres.fields import HStoreField
from django.db import models

from hub20.apps.core.exceptions import TransferError
from hub20.apps.core.fields import EthereumAddressField
from hub20.apps.core.models.transfers import Transfer, TransferConfirmation, TransferReceipt

from ..exceptions import RaidenPaymentError
from .raiden import Payment


class RaidenTransferReceipt(TransferReceipt):
    payment_data = HStoreField()


class RaidenTransferConfirmation(TransferConfirmation):
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE)


class RaidenTransfer(Transfer):
    address = EthereumAddressField(db_index=True)

    def _execute(self):
        try:
            from ..client import RaidenClient

            raiden_client = RaidenClient.select_for_transfer(
                amount=self.amount, address=self.address
            )
            payment_data = raiden_client.transfer(
                amount=self.as_token_amount,
                address=self.address,
                identifier=raiden_client._ensure_valid_identifier(self.identifier),
            )
            RaidenTransferReceipt.objects.create(transfer=self, payment_data=payment_data)
        except AssertionError:
            raise TransferError("Incorrect transfer method")
        except RaidenPaymentError as exc:
            raise TransferError(exc.message) from exc


__all__ = [
    "RaidenTransfer",
    "RaidenTransferReceipt",
    "RaidenTransferConfirmation",
]
