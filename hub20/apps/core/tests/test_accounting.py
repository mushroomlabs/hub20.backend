from decimal import Decimal

from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.core.factories import (
    BaseTokenFactory,
    InternalTransferFactory,
    PaymentConfirmationFactory,
    UserAccountFactory,
    UserFactory,
)
from hub20.apps.core.models.transfers import TransferCancellation


class AccountingTestCase(TestCase):
    def setUp(self):
        self.sender_account = UserAccountFactory()
        self.receiver_account = UserAccountFactory()
        self.sender = self.sender_account.user
        self.receiver = self.receiver_account.user

        self.deposit = PaymentConfirmationFactory(
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


class TokenBalanceViewTestCase(TestCase):
    def setUp(self):
        self.token = BaseTokenFactory()
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        PaymentConfirmationFactory(
            payment__route__deposit__user=self.user,
            payment__currency=self.token,
            payment__amount=10,
        )

    def test_balance_list_includes_token(self):
        response = self.client.get(reverse("balance-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_balance_view(self):
        response = self.client.get(
            reverse(
                "balance-detail",
                kwargs={"chain_id": self.token.chain_id, "address": self.token.address},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["amount"]), 10)


__all__ = ["AccountingTestCase", "InternalAccountingTestCase", "TokenBalanceViewTestCase"]
