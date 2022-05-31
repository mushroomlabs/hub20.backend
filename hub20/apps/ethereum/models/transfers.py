import logging

from django.db import models

from hub20.apps.core.fields import EthereumAddressField
from hub20.apps.core.models import (
    TokenAmount,
    Transfer,
    TransferConfirmation,
    TransferError,
    TransferReceipt,
)

from .blockchain import Transaction, TransactionDataRecord

logger = logging.getLogger(__name__)


class BlockchainTransfer(Transfer):
    address = EthereumAddressField(db_index=True)

    def _execute(self):
        try:
            from hub20.apps.ethereum.client.web3 import Web3Client

            web3_client = Web3Client.select_for_transfer(amount=self.amount, address=self.address)
            tx_data = web3_client.transfer(amount=self.as_token_amount, address=self.address)
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
