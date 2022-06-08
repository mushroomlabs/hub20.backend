from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.test import TestCase
from eth_utils import is_checksum_address

from hub20.apps.core.choices import TRANSFER_STATUS
from hub20.apps.core.factories import InternalPaymentNetworkFactory
from hub20.apps.core.models.accounting import PaymentNetworkAccount
from hub20.apps.core.settings import app_settings
from hub20.apps.core.tests import AccountingTestCase, TransferModelTestCase

from ..factories import (
    BaseWalletFactory,
    BlockchainPaymentNetworkFactory,
    BlockchainTransferConfirmationFactory,
    BlockchainTransferFactory,
    Erc20TokenBlockchainPaymentFactory,
    Erc20TokenBlockchainPaymentRouteFactory,
    Erc20TokenFactory,
    Erc20TokenPaymentConfirmationFactory,
    Erc20TokenTransactionDataFactory,
    Erc20TokenTransactionFactory,
    Erc20TokenTransferEventFactory,
    EtherAmountFactory,
    EtherPaymentConfirmationFactory,
    WalletBalanceRecordFactory,
)
from ..models import Block, BlockchainPayment, Web3Provider
from ..signals import block_sealed
from .mocks import BlockMock
from .utils import add_eth_to_account, add_token_to_account


class BlockchainPaymentTestCase(TestCase):
    def setUp(self):
        InternalPaymentNetworkFactory()
        self.blockchain_route = Erc20TokenBlockchainPaymentRouteFactory()
        self.order = self.blockchain_route.deposit
        self.chain = self.blockchain_route.chain

    def test_transaction_sets_payment_as_received(self):
        Erc20TokenTransferEventFactory(
            recipient=self.blockchain_route.account.address,
            transfer_amount=self.order.as_token_amount,
        )
        self.assertTrue(self.order.is_paid)
        self.assertFalse(self.order.is_confirmed)

    def test_transaction_creates_blockchain_payment(self):
        Erc20TokenTransferEventFactory(
            recipient=self.blockchain_route.account.address,
            transfer_amount=self.order.as_token_amount,
        )
        self.assertEqual(self.order.payments.count(), 1)

    def test_can_not_add_same_transaction_twice(self):
        payment = Erc20TokenBlockchainPaymentFactory(
            route=self.blockchain_route, payment_amount=self.order.as_token_amount
        )
        self.assertEqual(self.order.payments.count(), 1)
        with self.assertRaises(IntegrityError):
            BlockchainPayment.objects.create(
                transaction=payment.transaction,
                route=payment.route,
                amount=payment.amount,
                currency=payment.currency,
            )

    def test_user_balance_is_updated_on_completed_payment(self):
        payment = Erc20TokenBlockchainPaymentFactory(
            route=self.blockchain_route, payment_amount=self.order.as_token_amount
        )

        block_number = (
            payment.transaction.block.number + app_settings.Blockchain.minimum_confirmations
        )
        block_data = BlockMock(number=block_number)
        block_sealed.send(
            sender=Block, chain_id=payment.transaction.block.chain_id, block_data=block_data
        )

        balance_amount = self.order.user.account.get_balance_token_amount(self.order.currency)
        self.assertEqual(balance_amount, self.order.as_token_amount)


class BlockchainTransferTestCase(TransferModelTestCase):
    def setUp(self):
        super().setUp()
        confirmation = Erc20TokenPaymentConfirmationFactory(
            payment__route__deposit__user=self.sender,
        )
        self.credit = confirmation.payment.as_token_amount

        self.fee_amount = EtherAmountFactory()

        self.wallet = BaseWalletFactory()
        add_token_to_account(self.wallet, self.credit)
        add_eth_to_account(self.wallet, self.fee_amount)

        self.transfer = BlockchainTransferFactory(
            sender=self.sender, currency=self.credit.currency, amount=self.credit.amount
        )

    @patch.object(Web3Provider, "select_for_transfer")
    def test_external_transfers_fail_without_funds(self, select_for_transfer):
        select_for_transfer.side_effect = ValueError("no wallet available")
        self.transfer.execute()
        self.assertTrue(self.transfer.is_failed)
        self.assertEqual(self.transfer.status, TRANSFER_STATUS.failed)

    @patch.object(Web3Provider, "select_for_transfer")
    @patch.object(Web3Provider, "transfer")
    def test_transfers_can_be_processed_with_enough_balance(
        self, web3_execute_transfer, select_for_transfer
    ):
        select_for_transfer.return_value = self.wallet
        web3_execute_transfer.return_value = Erc20TokenTransactionDataFactory(
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
        self.wallet = BaseWalletFactory()
        self.treasury = PaymentNetworkAccount.make(network=self.hub)
        payment_confirmation = EtherPaymentConfirmationFactory()
        self.blockchain_account = PaymentNetworkAccount.make(
            network=payment_confirmation.payment.route.network.blockchainpaymentnetwork
        )
        self.credit = payment_confirmation.payment.as_token_amount

    @patch.object(Web3Provider, "select_for_transfer")
    @patch.object(Web3Provider, "transfer")
    def test_external_transfers_generate_accounting_entries_for_treasury_and_external_address(
        self, web3_execute_transfer, select_for_transfer
    ):
        transfer = BlockchainTransferFactory(
            sender=self.user, currency=self.credit.currency, amount=self.credit.amount
        )

        payout_tx_data = Erc20TokenTransactionDataFactory(
            amount=transfer.as_token_amount,
            recipient=transfer.address,
            from_address=self.wallet.address,
        )

        select_for_transfer.return_value = self.wallet
        web3_execute_transfer.return_value = payout_tx_data

        transfer.execute()

        # Transfer is executed, now we generate the transaction to create confirmation
        payout_tx = Erc20TokenTransactionFactory(
            hash=payout_tx_data.hash,
            amount=transfer.as_token_amount,
            recipient=transfer.address,
            from_address=self.wallet.address,
        )

        self.wallet.transactions.add(payout_tx)
        BlockchainTransferConfirmationFactory(transfer=transfer, transaction=payout_tx)

        transaction_type = ContentType.objects.get_for_model(payout_tx)

        blockchain_credit = self.blockchain_account.credits.filter(
            reference_type=transaction_type
        ).last()
        treasury_debit = self.treasury.debits.filter(reference_type=transaction_type).last()

        self.assertIsNotNone(treasury_debit)
        self.assertIsNotNone(blockchain_credit)

        self.assertEqual(treasury_debit.as_token_amount, blockchain_credit.as_token_amount)

    def test_blockchain_transfers_create_fee_entries(self):
        transfer = BlockchainTransferFactory(
            sender=self.user, currency=self.credit.currency, amount=self.credit.amount
        )

        with patch.object(Web3Provider, "select_for_transfer") as select:
            with patch.object(Web3Provider, "transfer") as web3_transfer_execute:
                payout_tx_data = Erc20TokenTransactionDataFactory(
                    amount=transfer.as_token_amount,
                    recipient=transfer.address,
                    from_address=self.wallet.address,
                )
                select.return_value = Web3Provider(self.wallet)
                web3_transfer_execute.return_value = payout_tx_data
                transfer.execute()

        payout_tx = Erc20TokenTransactionFactory(
            hash=payout_tx_data.hash,
            amount=transfer.as_token_amount,
            recipient=transfer.address,
            from_address=self.wallet.address,
        )

        BlockchainTransferConfirmationFactory(transfer=transfer, transaction=payout_tx)

        self.assertTrue(hasattr(transfer, "confirmation"))
        self.assertTrue(hasattr(transfer.confirmation, "blockchaintransferconfirmation"))

        transaction_fee = transfer.confirmation.blockchaintransferconfirmation.transaction.fee
        transaction_fee_type = ContentType.objects.get_for_model(transaction_fee)
        native_token = transaction_fee.currency

        sender_book = transfer.sender.account.get_book(token=native_token)

        entry_filters = dict(reference_type=transaction_fee_type, reference_id=transaction_fee.id)

        self.assertIsNotNone(sender_book.debits.filter(**entry_filters).last())
        self.assertIsNotNone(self.blockchain_account.credits.filter(**entry_filters).last())


class TransferEventTestCase(TestCase):
    def setUp(self):
        self.transfer_event = Erc20TokenTransferEventFactory()

    def test_can_get_token_amount(self):
        self.assertIsNotNone(self.transfer_event.as_token_amount)


class WalletTestCase(TestCase):
    def setUp(self):
        self.wallet = BaseWalletFactory()

    def test_address_is_checksummed(self):
        self.assertTrue(is_checksum_address(self.wallet.address))

    def test_can_read_current_balances(self):
        first_token = Erc20TokenFactory()
        second_token = Erc20TokenFactory()
        third_token = Erc20TokenFactory()

        WalletBalanceRecordFactory(wallet=self.wallet, currency=first_token, block__number=1)
        WalletBalanceRecordFactory(wallet=self.wallet, currency=second_token, block__number=1)

        # Let's create two more records for each token
        updated_first = WalletBalanceRecordFactory(
            wallet=self.wallet, currency=first_token, block__number=5
        )
        updated_second = WalletBalanceRecordFactory(
            wallet=self.wallet, currency=second_token, block__number=20
        )

        self.assertEqual(self.wallet.balances.count(), 2)
        self.assertTrue(updated_first in self.wallet.balances)
        self.assertTrue(updated_second in self.wallet.balances)

        WalletBalanceRecordFactory(wallet=self.wallet, currency=third_token, block__number=5)
        updated_third = WalletBalanceRecordFactory(
            wallet=self.wallet, currency=third_token, block__number=20
        )

        self.assertEqual(self.wallet.balances.count(), 3)
        self.assertTrue(updated_first in self.wallet.balances)
        self.assertTrue(updated_second in self.wallet.balances)
        self.assertTrue(updated_third in self.wallet.balances)


class BlockchainPaymentNetworkTestCase(TestCase):
    def test_payment_network_has_correct_type(self):
        network = BlockchainPaymentNetworkFactory()
        self.assertEqual(network.type, "ethereum")


__all__ = [
    "BlockchainPaymentNetworkTestCase",
    "BlockchainPaymentTestCase",
    "BlockchainTransferTestCase",
    "Web3AccountingTestCase",
    "TransferEventTestCase",
    "WalletTestCase",
]
