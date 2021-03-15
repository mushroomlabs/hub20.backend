from unittest.mock import Mock, patch

import pytest
from django.test import TestCase

from hub20.apps.blockchain.tests.mocks import (
    BlockWithTransactionDetailsMock,
    TransactionMock,
    Web3Mock,
)
from hub20.apps.core.factories import CheckoutFactory
from hub20.apps.blockchain.factories import ChainFactory
from hub20.apps.ethereum_money.models import EthereumToken
from hub20.apps.ethereum_money.client import process_latest_transfers
from hub20.apps.ethereum_money.tests.mocks import (
    EtherTransferDataMock,
    EtherTransferReceiptMock,
    Erc20TransferDataMock,
    Erc20TransferReceiptMock,
)


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class PaymentTransferTestCase(BaseTestCase):
    def setUp(self):
        self.w3 = Web3Mock
        self.block_filter = Mock()

    def test_can_detect_erc20_transfers(self):
        checkout = CheckoutFactory()
        token = checkout.currency

        route = checkout.routes.select_subclasses().first()

        self.assertIsNotNone(route)

        tx = TransactionMock(blockNumber=token.chain.highest_block, to=token.address)

        from_address = tx["from"]
        recipient = route.account.address
        amount = checkout.as_token_amount

        tx_data = Erc20TransferDataMock(
            from_address=from_address, recipient=recipient, amount=amount, **tx
        )

        tx_receipt = Erc20TransferReceiptMock(
            from_address=from_address, recipient=recipient, amount=amount, **tx
        )
        block_data = BlockWithTransactionDetailsMock(
            hash=tx_data.blockHash, number=tx_data.blockNumber, transactions=[tx_data]
        )

        with patch.object(self.block_filter, "get_new_entries", return_value=[block_data.hash]):
            with patch.object(self.w3.eth, "getBlock", return_value=block_data):
                with patch.object(
                    self.w3.eth, "waitForTransactionReceipt", return_value=tx_receipt
                ):
                    process_latest_transfers(self.w3, token.chain, self.block_filter)

        self.assertEqual(checkout.status, checkout.STATUS.paid)

    def test_can_detect_ether_transfers(self):
        chain = ChainFactory(synced=True)
        ETH = EthereumToken.ETH(chain=chain)

        checkout = CheckoutFactory(currency=ETH)
        route = checkout.routes.select_subclasses().first()

        self.assertIsNotNone(route)

        tx = TransactionMock(blockNumber=ETH.chain.highest_block, to=route.account.address)

        from_address = tx["from"]
        recipient = route.account.address
        amount = checkout.as_token_amount

        tx_data = EtherTransferDataMock(from_address=from_address, amount=amount, **tx)

        tx_receipt = EtherTransferReceiptMock(
            from_address=from_address, recipient=recipient, amount=amount, **tx
        )
        block_data = BlockWithTransactionDetailsMock(
            hash=tx_data.blockHash, number=tx_data.blockNumber, transactions=[tx_data]
        )

        with patch.object(self.block_filter, "get_new_entries", return_value=[block_data.hash]):
            with patch.object(self.w3.eth, "getBlock", return_value=block_data):
                with patch.object(
                    self.w3.eth, "waitForTransactionReceipt", return_value=tx_receipt
                ):
                    process_latest_transfers(self.w3, ETH.chain, self.block_filter)

        self.assertEqual(checkout.status, checkout.STATUS.paid)


__all__ = ["PaymentTransferTestCase"]
