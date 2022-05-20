from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.test import TestCase

from hub20.apps.core.choices import PAYMENT_NETWORKS, TRANSFER_STATUS
from hub20.apps.core.factories import BlockchainWithdrawalFactory, Erc20TokenPaymentOrderFactory
from hub20.apps.core.models.accounting import PaymentNetworkAccount
from hub20.apps.core.models.blockchain import Block, Transaction
from hub20.apps.core.models.payments import BlockchainPayment, BlockchainPaymentRoute
from hub20.apps.core.settings import app_settings
from hub20.apps.core.signals.tokens import outgoing_transfer_mined
from hub20.apps.core.tests import AccountingTestCase, TransferTestCase
from hub20.apps.core.tests.unit.base import add_eth_to_account, add_token_to_account
from hub20.apps.ethereum_money.factories import (
    Erc20TransactionDataFactory,
    Erc20TransactionFactory,
)

from ..client.web3 import Web3Client
from ..signals import block_sealed
from .mocks import BlockMock


@pytest.mark.django_db(transaction=True)
class BlockchainPaymentTestCase(TestCase):
    def setUp(self):
        self.order = Erc20TokenPaymentOrderFactory()
        self.blockchain_route = BlockchainPaymentRoute.make(deposit=self.order)
        self.chain = self.blockchain_route.chain

    def test_transaction_sets_payment_as_received(self):
        add_token_to_account(self.blockchain_route.account, self.order.as_token_amount)
        self.assertTrue(self.order.is_paid)
        self.assertFalse(self.order.is_confirmed)

    def test_transaction_creates_blockchain_payment(self):
        add_token_to_account(self.blockchain_route.account, self.order.as_token_amount)
        self.assertEqual(self.order.payments.count(), 1)

    def test_can_not_add_same_transaction_twice(self):
        add_token_to_account(self.blockchain_route.account, self.order.as_token_amount)
        self.assertEqual(self.order.payments.count(), 1)
        payment = self.order.payments.select_subclasses().first()
        with self.assertRaises(IntegrityError):
            BlockchainPayment.objects.create(
                transaction=payment.transaction,
                route=payment.route,
                amount=payment.amount,
                currency=payment.currency,
            )

    def test_user_balance_is_updated_on_completed_payment(self):
        tx = add_token_to_account(self.blockchain_route.account, self.order.as_token_amount)

        block_number = tx.block.number + app_settings.Payment.minimum_confirmations
        block_data = BlockMock(number=block_number)
        block_sealed.send(sender=Block, chain_id=tx.block.chain_id, block_data=block_data)

        balance_amount = self.order.user.account.get_balance_token_amount(self.order.currency)
        self.assertEqual(balance_amount, self.order.as_token_amount)


class BlockchainWithdrawalTestCase(TransferTestCase):
    def setUp(self):
        super().setUp()
        add_token_to_account(self.wallet, self.credit)
        add_eth_to_account(self.wallet, self.fee_amount)

        self.transfer = BlockchainWithdrawalFactory(
            sender=self.sender, currency=self.credit.currency, amount=self.credit.amount
        )

    @patch.object(Web3Client, "select_for_transfer")
    def test_external_transfers_fail_without_funds(self, select_for_transfer):
        select_for_transfer.side_effect = ValueError("no wallet available")
        self.transfer.execute()
        self.assertTrue(self.transfer.is_failed)
        self.assertEqual(self.transfer.status, TRANSFER_STATUS.failed)

    @patch.object(Web3Client, "select_for_transfer")
    @patch.object(Web3Client, "transfer")
    def test_transfers_can_be_processed_with_enough_balance(
        self, web3_execute_transfer, select_for_transfer
    ):
        select_for_transfer.return_value = Web3Client(self.wallet)
        web3_execute_transfer.return_value = Erc20TransactionDataFactory(
            amount=self.credit,
            from_address=self.wallet.address,
            recipient=self.transfer.address,
        )
        self.transfer.execute()
        self.assertTrue(self.transfer.is_processed)
        self.assertEqual(self.transfer.status, TRANSFER_STATUS.processed)


class Web3AccountingTestCase(AccountingTestCase):
    def setUp(self):
        super().setUp()
        self.treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
        self.blockchain_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.blockchain)

    @patch.object(Web3Client, "select_for_transfer")
    @patch.object(Web3Client, "transfer")
    def test_external_transfers_generate_accounting_entries_for_treasury_and_external_address(
        self, web3_execute_transfer, select_for_transfer
    ):
        transfer = BlockchainWithdrawalFactory(
            sender=self.sender, currency=self.credit.currency, amount=self.credit.amount
        )

        payout_tx_data = Erc20TransactionDataFactory(
            amount=transfer.as_token_amount,
            recipient=transfer.address,
            from_address=self.wallet.address,
        )

        select_for_transfer.return_value = Web3Client(self.wallet)
        web3_execute_transfer.return_value = payout_tx_data

        transfer.execute()

        # Transfer is executed, now we generate the transaction to get
        # the confirmation

        # TODO: make a more robust method to test mined transaction,
        # without relying on the knowledge from
        # outgoing_transfer_mined.

        payout_tx = Erc20TransactionFactory(
            hash=payout_tx_data.hash,
            amount=transfer.as_token_amount,
            recipient=transfer.address,
            from_address=self.wallet.address,
        )

        self.wallet.transactions.add(payout_tx)
        outgoing_transfer_mined.send(
            sender=Transaction,
            account=self.wallet,
            transaction=payout_tx,
            amount=transfer.as_token_amount,
            address=transfer.address,
        )

        transaction = transfer.confirmation.blockchainwithdrawalconfirmation.transaction
        transaction_type = ContentType.objects.get_for_model(transaction)

        blockchain_credit = self.blockchain_account.credits.filter(
            reference_type=transaction_type
        ).last()
        treasury_debit = self.treasury.debits.filter(reference_type=transaction_type).last()

        self.assertIsNotNone(treasury_debit)
        self.assertIsNotNone(blockchain_credit)

        self.assertEqual(treasury_debit.as_token_amount, blockchain_credit.as_token_amount)

    def test_blockchain_transfers_create_fee_entries(self):
        transfer = BlockchainWithdrawalFactory(
            sender=self.sender, currency=self.credit.currency, amount=self.credit.amount
        )

        with patch.object(Web3Client, "select_for_transfer") as select:
            with patch.object(Web3Client, "transfer") as web3_transfer_execute:
                payout_tx_data = Erc20TransactionDataFactory(
                    amount=transfer.as_token_amount,
                    recipient=transfer.address,
                    from_address=self.wallet.address,
                )
                select.return_value = Web3Client(self.wallet)
                web3_transfer_execute.return_value = payout_tx_data
                transfer.execute()

        payout_tx = Erc20TransactionFactory(
            hash=payout_tx_data.hash,
            amount=transfer.as_token_amount,
            recipient=transfer.address,
            from_address=self.wallet.address,
        )

        outgoing_transfer_mined.send(
            sender=Transaction,
            account=self.wallet,
            amount=transfer.as_token_amount,
            address=transfer.address,
            transaction=payout_tx,
        )

        self.assertTrue(hasattr(transfer, "confirmation"))
        self.assertTrue(hasattr(transfer.confirmation, "blockchainwithdrawalconfirmation"))

        transaction = transfer.confirmation.blockchainwithdrawalconfirmation.transaction
        transaction_type = ContentType.objects.get_for_model(transaction)
        native_token = transfer.confirmation.blockchainwithdrawalconfirmation.fee.currency

        sender_book = transfer.sender.account.get_book(token=native_token)

        entry_filters = dict(reference_type=transaction_type, reference_id=transaction.id)

        self.assertIsNotNone(sender_book.debits.filter(**entry_filters).last())
        self.assertIsNotNone(self.blockchain_account.credits.filter(**entry_filters).last())
