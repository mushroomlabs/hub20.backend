from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from hub20.apps.core.factories import Erc20TokenPaymentOrderFactory, RaidenWithdrawalFactory
from hub20.apps.core.models import PaymentNetwork, PaymentNetworkAccount
from hub20.apps.core.tests import AccountingTestCase

from ..client.node import RaidenClient
from ..factories import ChannelFactory, PaymentEventFactory, TokenNetworkFactory
from ..models import RaidenPaymentRoute


class RaidenPaymentTestCase(TestCase):
    def setUp(self):
        token_network = TokenNetworkFactory()

        self.channel = ChannelFactory(token_network=token_network)
        self.order = Erc20TokenPaymentOrderFactory(currency=token_network.token)
        self.raiden_route = RaidenPaymentRoute.make(deposit=self.order)

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


class RaidenAccountingTestCase(AccountingTestCase):
    def setUp(self):
        super().setUp()
        self.treasury = PaymentNetworkAccount.make(PaymentNetwork._meta.app_label)
        self.raiden_account = PaymentNetworkAccount.make(RaidenPaymentRoute._meta.app_label)

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
