import logging

from django.core.exceptions import ValidationError
from django.db import models

from hub20.apps.core.models import (
    TokenAmount,
    Transfer,
    TransferConfirmation,
    TransferError,
    TransferReceipt,
)

from ..constants import NULL_ADDRESS, SENTINEL_ADDRESS
from .blockchain import Transaction, TransactionDataRecord
from .fields import EthereumAddressField
from .networks import BlockchainPaymentNetwork
from .tokens import Erc20Token

logger = logging.getLogger(__name__)


class BlockchainTransfer(Transfer):
    NETWORK = BlockchainPaymentNetwork
    address = EthereumAddressField(db_index=True)

    def clean(self):

        if not self.address:
            raise ValidationError("Transfer has no valid address defined")

        if token := Erc20Token.objects.filter(address=self.address).first():
            raise ValidationError(
                f"{token.address} is a token address (token.symbol), not the destination"
            )

        if self.address in [NULL_ADDRESS, SENTINEL_ADDRESS]:
            raise ValidationError(f"{self.address} is not a valid target address for transfers")

    def _execute(self):
        try:
            assert self.provider is not None, "No active provider to execute transfer"

            account = self.provider.select_for_transfer(self.as_token_amount)
            assert account is not None, "No account with enough balance to cover"
            tx_data: TransactionDataRecord = self.provider.transfer(
                account=account, amount=self.as_token_amount, address=self.address
            )
            BlockchainTransferReceipt.objects.create(transfer=self, transaction_data=tx_data)
        except Exception as exc:
            raise TransferError(str(exc)) from exc


class BlockchainTransferReceipt(TransferReceipt):
    transaction_data = models.OneToOneField(TransactionDataRecord, on_delete=models.CASCADE)


class BlockchainTransferConfirmation(TransferConfirmation):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE)

    @property
    def fee(self) -> TokenAmount:
        native_token = self.transaction.block.chain.native_token
        return native_token.from_wei(self.transaction.gas_fee)


__all__ = [
    "BlockchainTransfer",
    "BlockchainTransferConfirmation",
    "BlockchainTransferReceipt",
]
