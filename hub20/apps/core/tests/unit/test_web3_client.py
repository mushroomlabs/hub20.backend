from unittest.mock import patch

import pytest
from django.test import TestCase

from hub20.apps.blockchain.factories import TransactionFactory
from hub20.apps.blockchain.tests.mocks import Web3Mock
from hub20.apps.core.factories import CheckoutFactory
from hub20.apps.ethereum_money.client import (
    encode_transfer_data,
    process_incoming_erc20_transfer_event,
)
from hub20.apps.ethereum_money.tests.mocks import Erc20LogFilterMock


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class PaymentTransferTestCase(BaseTestCase):
    def setUp(self):
        self.w3 = Web3Mock

    @patch("hub20.apps.ethereum_money.client.get_transaction_by_hash")
    def test_can_detect_erc20_transfers(self, get_transaction_mock):

        checkout = CheckoutFactory()
        route = checkout.routes.select_subclasses().first()

        self.assertIsNotNone(route)

        recipient = route.account.address

        tx_filter_entry = Erc20LogFilterMock(
            blockNumber=checkout.currency.chain.highest_block,
            recipient=recipient,
            amount=checkout.as_token_amount,
        )

        get_transaction_mock.return_value = TransactionFactory(
            from_address=tx_filter_entry["args"]["_from"],
            to_address=checkout.currency.address,
            data=encode_transfer_data(recipient, checkout.as_token_amount),
        )

        process_incoming_erc20_transfer_event(
            w3=self.w3, token=checkout.currency, account=route.account, event=tx_filter_entry
        )

        self.assertEqual(checkout.status, checkout.STATUS.paid)


__all__ = ["PaymentTransferTestCase"]
