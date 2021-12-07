import pytest
from django.test import TestCase

from hub20.apps.blockchain.tests.mocks import BlockMock, Web3Mock
from hub20.apps.core.factories import CheckoutFactory
from hub20.apps.ethereum_money.tasks import record_token_transfers
from hub20.apps.ethereum_money.tests.mocks import Erc20TransferDataMock, Erc20TransferReceiptMock


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class PaymentTransferTestCase(BaseTestCase):
    def setUp(self):
        self.w3 = Web3Mock

    def test_can_detect_erc20_transfers(self):

        checkout = CheckoutFactory()
        route = checkout.routes.select_subclasses().first()

        self.assertIsNotNone(route)

        transaction_params = dict(
            blockNumber=checkout.currency.chain.highest_block,
            recipient=route.account.address,
            amount=checkout.as_token_amount,
        )

        tx_data = Erc20TransferDataMock(**transaction_params)
        transaction_receipt = Erc20TransferReceiptMock(
            hash=tx_data.hash,
            blockHash=tx_data.blockHash,
            from_address=tx_data["from"],
            transactionIndex=tx_data.transactionIndex,
            **transaction_params,
        )
        block_data = BlockMock(
            hash=tx_data.blockHash, number=tx_data.blockNumber, transactions=[tx_data.hash]
        )

        record_token_transfers(
            chain_id=self.w3.eth.chain_id,
            block_data=block_data,
            transaction_data=tx_data,
            transaction_receipt=transaction_receipt,
        )

        self.assertEqual(checkout.status, checkout.STATUS.paid)


__all__ = ["PaymentTransferTestCase"]
