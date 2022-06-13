from __future__ import annotations

from django.contrib.postgres.fields import HStoreField
from django.db import models

from hub20.apps.core.exceptions import TransferError
from hub20.apps.core.models.networks import PaymentNetwork_T
from hub20.apps.core.models.transfers import Transfer, TransferConfirmation, TransferReceipt
from hub20.apps.ethereum.models import EthereumAddressField

from ..exceptions import RaidenPaymentError
from .networks import RaidenPaymentNetwork
from .raiden import Payment, Raiden


class RaidenTransferReceipt(TransferReceipt):
    payment_data = HStoreField()


class RaidenTransferConfirmation(TransferConfirmation):
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE)


class RaidenTransfer(Transfer):
    NETWORK: PaymentNetwork_T = RaidenPaymentNetwork
    address = EthereumAddressField(db_index=True)

    def _execute(self):
        if not hasattr(self.currency.subclassed, "tokennetwork"):
            raise TransferError(f"token {self.currency} is not available on Raiden")

        funded_nodes = Raiden.objects.filter(
            channels__token_network__token=self.currency, channels__balance__gte=self.amount
        )

        raiden = funded_nodes.order_by("?").first()

        if raiden is None:
            raise TransferError("No funds available on the any of the connected raiden nodes")

        provider = raiden.provider

        try:
            assert provider.is_online, f"{provider.raiden.hostname} is not available"
        except AssertionError as exc:
            raise TransferError(str(exc)) from exc

        try:
            identifier = provider._ensure_valid_identifier(self.identifier)
            payment_data = raiden.provider.transfer(
                amount=self.as_token_amount,
                address=self.address,
                identifier=identifier,
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
