from django.test import TestCase

from hub20.apps.core.factories import (
    Erc20TokenPaymentConfirmationFactory,
    InternalTransferFactory,
    UserAccountFactory,
)
from hub20.apps.core.models.transfers import TransferCancellation


class AccountingTestCase(TestCase):
    def setUp(self):
        self.sender_account = UserAccountFactory()
        self.receiver_account = UserAccountFactory()
        self.sender = self.sender_account.user
        self.receiver = self.receiver_account.user

        self.deposit = Erc20TokenPaymentConfirmationFactory(
            payment__route__deposit__user=self.sender,
        )

        self.credit = self.deposit.payment.as_token_amount


class InternalAccountingTestCase(AccountingTestCase):
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
