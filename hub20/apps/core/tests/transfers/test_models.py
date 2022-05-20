from django.test import TestCase

from hub20.apps.core.choices import TRANSFER_STATUS
from hub20.apps.core.factories import (
    Erc20TokenPaymentConfirmationFactory,
    InternalTransferFactory,
    UserAccountFactory,
)


class TransferTestCase(TestCase):
    def setUp(self):
        self.sender_account = UserAccountFactory()
        self.receiver_account = UserAccountFactory()
        self.sender = self.sender_account.user
        self.receiver = self.receiver_account.user

        self.deposit = Erc20TokenPaymentConfirmationFactory(
            payment__route__deposit__user=self.sender,
        )

        self.credit = self.deposit.payment.as_token_amount


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
