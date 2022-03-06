from unittest.mock import patch

import pytest
from django.test import TestCase

from hub20.apps.blockchain.tests.mocks import BlockMock, Web3Mock
from hub20.apps.core.factories import CheckoutFactory
from hub20.apps.ethereum_money.tasks import record_token_transfers
from hub20.apps.ethereum_money.tests.mocks import (
    Erc20LogFilterMock,
    Erc20TransferDataMock,
    Erc20TransferReceiptMock,
)


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class PaymentTransferTestCase(BaseTestCase):
    def setUp(self):
        self.w3 = Web3Mock

    @patch("hub20.apps.ethereum_money.tasks.Web3Provider")
    @patch("hub20.apps.ethereum_money.tasks.make_web3")
    def test_can_detect_erc20_transfers(self, make_web3_mock, MockWeb3Provider):

        checkout = CheckoutFactory()
        route = checkout.routes.select_subclasses().first()

        self.assertIsNotNone(route)

        transaction_params = dict(
            blockNumber=checkout.currency.chain.highest_block,
            recipient=route.account.address,
            amount=checkout.as_token_amount,
        )

        tx_data = Erc20TransferDataMock(**transaction_params)
        tx_receipt = Erc20TransferReceiptMock(
            hash=tx_data.hash,
            blockHash=tx_data.blockHash,
            from_address=tx_data["from"],
            transactionIndex=tx_data.transactionIndex,
            **transaction_params,
        )
        block_data = BlockMock(
            hash=tx_data.blockHash, number=tx_data.blockNumber, transactions=[tx_data.hash]
        )

        event_data = Erc20LogFilterMock(
            transactionHash=tx_data.hash,
            amount=checkout.as_token_amount,
            recipient=route.account.address,
        )

        make_web3_mock.return_value = self.w3
        self.w3.eth.get_transaction.return_value = tx_data
        self.w3.eth.get_transaction_receipt.return_value = tx_receipt
        self.w3.eth.get_block.return_value = block_data

        record_token_transfers(
            chain_id=self.w3.eth.chain_id,
            event_data=event_data,
            provider_url=self.w3.provider.endpoint_uri,
        )

        self.assertEqual(checkout.status, checkout.STATUS.paid)


__all__ = ["PaymentTransferTestCase"]
