import logging

from django.db import models

from hub20.apps.core.models import (
    PaymentNetwork_T,
    TokenAmount,
    Transfer,
    TransferConfirmation,
    TransferError,
    TransferReceipt,
)

from .accounts import EthereumAccount_T
from .blockchain import Transaction, TransactionDataRecord
from .fields import EthereumAddressField
from .networks import BlockchainPaymentNetwork

logger = logging.getLogger(__name__)


class BlockchainTransfer(Transfer):
    NETWORK: PaymentNetwork_T = BlockchainPaymentNetwork
    address = EthereumAddressField(db_index=True)

    def _execute(self):
        try:
            assert self.provider is not None, "No active provider to execute transfer"

            account: EthereumAccount_T = self.provider.select_for_transfer(self.as_token_amount)
            assert account is not None, "No account with enough balance to cover"
            tx_data: TransactionDataRecord = self.provider.transfer(
                amount=self.as_token_amount, address=self.address
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
