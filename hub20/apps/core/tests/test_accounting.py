from decimal import Decimal

from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.core.factories import (
    InternalPaymentNetworkFactory,
    InternalTransferFactory,
    PaymentConfirmationFactory,
    UserAccountFactory,
)
from hub20.apps.core.models.transfers import TransferCancellation


class AccountingTestCase(TestCase):
    def setUp(self):
        self.hub = InternalPaymentNetworkFactory()
        self.user_account = UserAccountFactory()
        self.user = self.user_account.user

        self.payment_confirmation = PaymentConfirmationFactory(
            payment__route__deposit__user=self.user
        )

        self.credit = self.payment_confirmation.payment.as_token_amount


class InternalAccountingTestCase(AccountingTestCase):
    def test_cancelled_transfer_generate_refunds(self):
        receiver_account = UserAccountFactory()
        transfer = InternalTransferFactory(
            sender=self.user,
            receiver=receiver_account.user,
            currency=self.credit.currency,
            amount=self.credit.amount,
        )
        cancellation = TransferCancellation.objects.create(
            transfer=transfer, canceled_by=self.user
        )

        sender_balance_amount = self.user.account.get_balance_token_amount(
            token=self.credit.currency
        )
        self.assertEqual(sender_balance_amount, self.credit)
        last_treasury_debit = self.hub.account.debits.last()

        self.assertEqual(last_treasury_debit.reference, cancellation)


class TokenBalanceViewTestCase(AccountingTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_balance_list_includes_token(self):
        response = self.client.get(reverse("balance-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_balance_view(self):
        token = self.payment_confirmation.payment.currency
        amount = self.payment_confirmation.payment.amount
        response = self.client.get(reverse("balance-detail", kwargs={"pk": token.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["amount"]), amount)


__all__ = ["AccountingTestCase", "InternalAccountingTestCase", "TokenBalanceViewTestCase"]
