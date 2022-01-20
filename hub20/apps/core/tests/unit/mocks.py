from decimal import Decimal
from unittest.mock import MagicMock

from hub20.apps.blockchain.models import Transaction
from hub20.apps.core.choices import PAYMENT_NETWORKS
from hub20.apps.core.models import (
    BlockchainTransferExecutor,
    RaidenTransferExecutor,
    Transfer,
    TransferReceipt,
)
from hub20.apps.ethereum_money.factories import Erc20TransferFactory, EtherAmountFactory
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.ethereum_money.signals import outgoing_transfer_mined
from hub20.apps.raiden.factories import ChannelFactory, PaymentEventFactory


class MockBlockchainTransferExecutor(BlockchainTransferExecutor):
    def __init__(self, account, w3=None):
        self.account = account
        self.w3 = MagicMock()

    def execute(self, transfer: Transfer):
        tx = Erc20TransferFactory(
            recipient=transfer.address,
            from_address=self.account.address,
            amount=transfer.as_token_amount,
        )
        TransferReceipt.objects.create(
            transfer=transfer, network=PAYMENT_NETWORKS.blockchain, identifier=tx.hash
        )

        outgoing_transfer_mined.send(
            sender=Transaction,
            account=self.account,
            transaction=tx,
            amount=transfer.as_token_amount,
            address=transfer.address,
        )

    @classmethod
    def estimate_transfer_fees(cls, *args, **kw):
        return mock_fee_estimation()


class MockRaidenTransferExecutor(RaidenTransferExecutor):
    def execute(self, transfer: Transfer):
        identifier = self._ensure_valid_identifier(transfer.identifier)
        TransferReceipt.objects.create(
            transfer=transfer, network=PAYMENT_NETWORKS.raiden, identifier=identifier
        )
        channel = ChannelFactory(
            raiden=self.raiden, token_network__token=transfer.currency, balance=transfer.amount
        )
        params = dict(
            amount=transfer.amount,
            channel=channel,
            sender_address=self.raiden.address,
            receiver_address=transfer.address,
        )

        if identifier:
            params.update(dict(identifier=identifier))

        payment = PaymentEventFactory(**params)
        return str(payment.identifier)

    def transfer(self, *args, **kw):
        pass

    def __init__(self, account):
        self.raiden = account


def mock_fee_estimation() -> EthereumTokenAmount:
    return EtherAmountFactory(amount=Decimal("0.001"))
