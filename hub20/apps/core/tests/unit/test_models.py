from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from hub20.apps.blockchain.models import Block, Transaction
from hub20.apps.blockchain.signals import block_sealed
from hub20.apps.blockchain.tests.mocks import BlockMock
from hub20.apps.core.choices import PAYMENT_NETWORKS, TRANSFER_STATUS
from hub20.apps.core.factories import (
    BlockchainWithdrawalFactory,
    CheckoutFactory,
    Erc20TokenPaymentConfirmationFactory,
    Erc20TokenPaymentOrderFactory,
    InternalTransferFactory,
    RaidenWithdrawalFactory,
    StoreFactory,
    UserAccountFactory,
)
from hub20.apps.core.models.accounting import PaymentNetworkAccount
from hub20.apps.core.models.payments import (
    BlockchainPayment,
    BlockchainPaymentRoute,
    RaidenPaymentRoute,
)
from hub20.apps.core.models.transfers import RaidenClient, TransferCancellation, Web3Client
from hub20.apps.core.settings import app_settings
from hub20.apps.ethereum_money.factories import (
    Erc20TransactionDataFactory,
    Erc20TransactionFactory,
    EtherAmountFactory,
)
from hub20.apps.ethereum_money.signals import outgoing_transfer_mined
from hub20.apps.ethereum_money.tests.base import add_eth_to_account, add_token_to_account
from hub20.apps.raiden.factories import (
    ChannelFactory,
    PaymentEventFactory,
    RaidenFactory,
    TokenNetworkFactory,
)
from hub20.apps.wallet.factories import EthereumAccountFactory


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class BlockchainPaymentTestCase(BaseTestCase):
    def setUp(self):
        self.order = Erc20TokenPaymentOrderFactory()
        self.blockchain_route = BlockchainPaymentRoute.objects.filter(deposit=self.order).first()
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


class CheckoutTestCase(BaseTestCase):
    def setUp(self):
        self.checkout = CheckoutFactory()
        self.checkout.store.accepted_token_list.tokens.add(self.checkout.currency)

    def test_checkout_user_and_store_owner_are_the_same(self):
        self.assertEqual(self.checkout.store.owner, self.checkout.user)

    def test_checkout_currency_must_be_accepted_by_store(self):
        self.checkout.clean()

        self.checkout.store.accepted_token_list.tokens.clear()
        with self.assertRaises(ValidationError):
            self.checkout.clean()


class RaidenPaymentTestCase(BaseTestCase):
    def setUp(self):
        token_network = TokenNetworkFactory()

        self.channel = ChannelFactory(token_network=token_network)
        self.order = Erc20TokenPaymentOrderFactory(currency=token_network.token)
        self.raiden_route = RaidenPaymentRoute.objects.filter(deposit=self.order).first()

    def test_order_has_raiden_route(self):
        self.assertIsNotNone(self.raiden_route)

    def test_payment_via_raiden_sets_order_as_paid(self):
        PaymentEventFactory(
            channel=self.channel,
            amount=self.order.amount,
            identifier=self.raiden_route.identifier,
            receiver_address=self.channel.raiden.address,
        )
        self.assertTrue(self.order.is_paid)


class StoreTestCase(BaseTestCase):
    def setUp(self):
        self.store = StoreFactory()

    def test_store_rsa_keys_are_valid_pem(self):
        self.assertIsNotNone(self.store.rsa.pk)
        self.assertTrue(type(self.store.rsa.public_key_pem) is str)
        self.assertTrue(type(self.store.rsa.private_key_pem) is str)

        self.assertTrue(self.store.rsa.public_key_pem.startswith("-----BEGIN PUBLIC KEY-----"))
        self.assertTrue(
            self.store.rsa.private_key_pem.startswith("-----BEGIN RSA PRIVATE KEY-----")
        )


class TransferTestCase(BaseTestCase):
    def setUp(self):
        self.sender_account = UserAccountFactory()
        self.receiver_account = UserAccountFactory()
        self.sender = self.sender_account.user
        self.receiver = self.receiver_account.user

        self.deposit = Erc20TokenPaymentConfirmationFactory(
            payment__route__deposit__user=self.sender,
        )

        self.credit = self.deposit.payment.as_token_amount
        self.wallet = EthereumAccountFactory()
        self.fee_amount = EtherAmountFactory(amount=Decimal("0.001"))
        self.chain = self.fee_amount.currency.chain
        self.treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
        self.blockchain_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.blockchain)
        self.raiden_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.raiden)
        self.raiden = RaidenFactory()


class InternalTransferTestCase(TransferTestCase):
    def test_transfers_are_finalized_as_confirmed(self):
        transfer = InternalTransferFactory(
            sender=self.sender,
            receiver=self.receiver,
            currency=self.credit.currency,
            amount=self.credit.amount,
        )

        transfer.execute()
        self.assertTrue(transfer.is_finalized)
        self.assertEqual(transfer.status, TRANSFER_STATUS.confirmed)
        self.assertTrue(transfer.is_confirmed)

    def test_transfers_change_balance(self):
        transfer = InternalTransferFactory(
            sender=self.sender,
            receiver=self.receiver,
            currency=self.credit.currency,
            amount=self.credit.amount,
        )

        transfer.execute()
        self.assertTrue(transfer.is_finalized)

        sender_balance = self.sender_account.get_balance_token_amount(self.credit.currency)
        receiver_balance = self.receiver_account.get_balance_token_amount(self.credit.currency)

        self.assertEqual(sender_balance.amount, 0)
        self.assertEqual(receiver_balance, self.credit)

    def test_transfers_fail_with_low_sender_balance(self):
        transfer = InternalTransferFactory(
            sender=self.sender,
            receiver=self.receiver,
            currency=self.credit.currency,
            amount=2 * self.credit.amount,
        )

        transfer.execute()
        self.assertTrue(transfer.is_finalized)
        self.assertEqual(transfer.status, TRANSFER_STATUS.failed)


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


class TransferAccountingTestCase(TransferTestCase):
    def test_cancelled_transfer_generate_refunds(self):
        transfer = InternalTransferFactory(
            sender=self.sender,
            receiver=self.receiver,
            currency=self.credit.currency,
            amount=self.credit.amount,
        )
        cancellation = TransferCancellation.objects.create(
            transfer=transfer, canceled_by=self.sender
        )

        sender_balance_amount = self.sender.account.get_balance_token_amount(
            token=self.credit.currency
        )
        self.assertEqual(sender_balance_amount, self.credit)
        last_treasury_debit = self.treasury.debits.last()

        self.assertEqual(last_treasury_debit.reference, cancellation)

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

    @patch.object(RaidenClient, "select_for_transfer")
    @patch.object(RaidenClient, "transfer")
    def test_raiden_transfers_create_entries_for_raiden_account_and_treasury(
        self, raiden_transfer, select_for_transfer
    ):
        transfer = RaidenWithdrawalFactory(
            sender=self.sender,
            currency=self.credit.currency,
            amount=self.credit.amount,
        )
        channel = ChannelFactory(token_network__token=self.credit.currency)

        raiden_payment = PaymentEventFactory.build(
            amount=self.credit.amount,
            channel=channel,
            sender_address=self.raiden.account.address,
            receiver_address=transfer.address,
            identifier=transfer.identifier,
        )
        select_for_transfer.return_value = RaidenClient(raiden_node=self.raiden)
        raiden_transfer.return_value = dict(identifier=raiden_payment.identifier)

        transfer.execute()

        raiden_payment.save()

        self.assertTrue(hasattr(transfer, "confirmation"))
        self.assertTrue(hasattr(transfer.confirmation, "raidenwithdrawalconfirmation"))
        self.assertIsNotNone(transfer.confirmation.raidenwithdrawalconfirmation.payment)

        payment = transfer.confirmation.raidenwithdrawalconfirmation.payment
        transfer_type = ContentType.objects.get_for_model(transfer)

        self.assertEqual(payment.receiver_address, transfer.address)

        transfer_filter = dict(reference_type=transfer_type, reference_id=transfer.id)

        self.assertIsNotNone(self.treasury.debits.filter(**transfer_filter).last())
        self.assertIsNotNone(self.raiden_account.credits.filter(**transfer_filter).last())


__all__ = [
    "BlockchainPaymentTestCase",
    "CheckoutTestCase",
    "RaidenPaymentTestCase",
    "StoreTestCase",
    "TransferTestCase",
    "InternalTransferTestCase",
    "BlockchainWithdrawalTestCase",
    "TransferAccountingTestCase",
]
