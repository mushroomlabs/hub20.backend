from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from hub20.apps.core.choices import TRANSFER_STATUS
from hub20.apps.core.factories import (
    FAKER,
    BaseTokenFactory,
    InternalPaymentNetworkFactory,
    InternalTransferFactory,
    PaymentConfirmationFactory,
    UserAccountFactory,
    UserFactory,
)
from hub20.apps.core.models import Transfer, TransferConfirmation


class BaseTransferTestCase(TestCase):
    def setUp(self):
        InternalPaymentNetworkFactory()


class TransferManagerTestCase(BaseTransferTestCase):
    def test_pending_query_manager(self):
        self.transfer = InternalTransferFactory()

        self.assertTrue(Transfer.pending.exists())

        # Confirmed transfers are no longer pending
        TransferConfirmation.objects.create(transfer=self.transfer)
        self.assertTrue(Transfer.confirmed.exists())
        self.assertFalse(Transfer.pending.exists())

        # Another transfer shows up, and already confirmed transfers are out
        another_transfer = InternalTransferFactory()
        self.assertTrue(Transfer.pending.exists())
        self.assertEqual(Transfer.pending.count(), 1)
        self.assertEqual(Transfer.pending.select_subclasses().first(), another_transfer)


class TransferModelTestCase(BaseTransferTestCase):
    def setUp(self):
        super().setUp()
        self.sender_account = UserAccountFactory()
        self.receiver_account = UserAccountFactory()
        self.sender = self.sender_account.user
        self.receiver = self.receiver_account.user

        self.deposit = PaymentConfirmationFactory(
            payment__route__deposit__user=self.sender,
        )

        self.credit = self.deposit.payment.as_token_amount


class InternalTransferTestCase(TransferModelTestCase):
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


class TransferViewTestCase(BaseTransferTestCase):
    def setUp(self):
        super().setUp()
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.token = BaseTokenFactory()
        self.target_address = FAKER.ethereum_address()

    def test_no_balance_returns_error(self):
        response = self.client.post(
            reverse("user-transfer-list"),
            {
                "address": self.target_address,
                "payment_network": "blockchain",
                "amount": 10,
                "token": reverse("token-detail", kwargs=dict(pk=self.token.pk)),
            },
        )
        self.assertEqual(response.status_code, 400)

        self.assertTrue("non_field_errors" in response.data.keys())
        self.assertEqual(len(response.data["non_field_errors"]), 1)

        error_details = response.data["non_field_errors"][0]
        self.assertEqual(error_details.code, "invalid")

    def test_insufficient_balance_returns_error(self):
        TRANSFER_AMOUNT = 10

        PaymentConfirmationFactory(
            payment__route__deposit__user=self.user,
            payment__currency=self.token,
            payment__amount=TRANSFER_AMOUNT / 2,
        )

        response = self.client.post(
            reverse("user-transfer-list"),
            {
                "address": self.target_address,
                "payment_network": "blockchain",
                "amount": TRANSFER_AMOUNT,
                "token": reverse(
                    "token-detail",
                    kwargs=dict(pk=self.token.pk),
                ),
            },
        )
        self.assertEqual(response.status_code, 400)

        self.assertTrue("non_field_errors" in response.data.keys())
        self.assertEqual(len(response.data["non_field_errors"]), 1)

        error_details = response.data["non_field_errors"][0]
        self.assertEqual(error_details.code, "insufficient")


__all__ = [
    "BaseTransferTestCase",
    "TransferManagerTestCase",
    "TransferModelTestCase",
    "InternalTransferTestCase",
    "TransferViewTestCase",
]
