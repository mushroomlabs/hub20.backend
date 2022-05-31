from unittest.mock import patch

import pytest
from django.test import TestCase

from hub20.apps.core.factories import InternalPaymentNetworkFactory
from hub20.apps.ethereum.tasks import record_token_transfers
from hub20.apps.ethereum.tests.mocks import (
    BlockMock,
    Erc20LogFilterMock,
    Erc20TransferDataMock,
    Erc20TransferReceiptMock,
    Web3Mock,
)

from ..factories import (
    Erc20TokenBlockchainPaymentRouteFactory,
    Erc20TokenCheckoutFactory,
    Web3ProviderFactory,
)


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class PaymentTransferTestCase(BaseTestCase):
    def setUp(self):
        self.hub = InternalPaymentNetworkFactory()
        self.provider = Web3ProviderFactory()
        self.w3 = Web3Mock

    @patch("hub20.apps.ethereum.tasks.Web3Provider")
    def test_can_detect_erc20_transfers(self, MockWeb3ProviderModel):
        checkout = Erc20TokenCheckoutFactory()
        route = Erc20TokenBlockchainPaymentRouteFactory(deposit=checkout.order)

        self.assertIsNotNone(route)

        transaction_params = dict(
            blockNumber=checkout.order.currency.chain.highest_block,
            recipient=route.account.address,
            amount=checkout.order.as_token_amount,
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
            amount=checkout.order.as_token_amount,
            recipient=route.account.address,
        )

        self.w3.eth.get_transaction.return_value = tx_data
        self.w3.eth.get_transaction_receipt.return_value = tx_receipt
        self.w3.eth.get_block.return_value = block_data

        self.provider._make_web3 = lambda: self.w3

        MockWeb3ProviderModel.objects.get.return_value = self.provider
        record_token_transfers(
            chain_id=self.w3.eth.chain_id,
            wallet_address=route.account.address,
            event_data=event_data,
            provider_url=self.provider.url,
        )

        self.assertEqual(checkout.order.status, checkout.order.STATUS.paid)


__all__ = ["PaymentTransferTestCase"]
