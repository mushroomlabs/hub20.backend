from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from hub20.apps.core.factories import InternalPaymentNetworkFactory
from hub20.apps.core.tests import AccountingTestCase
from hub20.apps.ethereum.factories import Erc20TokenPaymentOrderFactory

from ..factories import (
    ChannelFactory,
    PaymentEventFactory,
    RaidenFactory,
    RaidenPaymentFactory,
    RaidenTransferFactory,
    TokenNetworkFactory,
)
from ..models import RaidenPaymentRoute, RaidenProvider


class RaidenPaymentTestCase(TestCase):
    def setUp(self):
        InternalPaymentNetworkFactory()
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
        raiden = RaidenFactory()
        raiden_network = raiden.chain.raidenpaymentnetwork
        self.treasury = self.hub.account
        self.raiden_account = raiden_network.account

        raiden_deposit = RaidenPaymentFactory(
            route__deposit__user=self.user,
        )
        self.credit = raiden_deposit.as_token_amount

    @patch.object(RaidenProvider, "is_online")
    @patch.object(RaidenProvider, "transfer")
    def test_raiden_transfers_create_entries_for_raiden_account_and_treasury(
        self, raiden_transfer, is_online
    ):
        transfer = RaidenTransferFactory(
            sender=self.user,
            currency=self.credit.currency,
            amount=self.credit.amount,
        )
        channel = ChannelFactory(token_network__token=self.credit.currency)

        raiden_payment = PaymentEventFactory.build(
            amount=self.credit.amount,
            channel=channel,
            sender_address=channel.raiden.address,
            receiver_address=transfer.address,
            identifier=transfer.identifier,
        )
        is_online.return_value = True
        raiden_transfer.return_value = dict(identifier=raiden_payment.identifier)

        transfer.execute()

        raiden_payment.save()

        self.assertTrue(hasattr(transfer, "confirmation"))
        self.assertTrue(hasattr(transfer.confirmation, "raidentransferconfirmation"))
        self.assertIsNotNone(transfer.confirmation.raidentransferconfirmation.payment)

        payment = transfer.confirmation.raidentransferconfirmation.payment
        transfer_type = ContentType.objects.get_for_model(transfer)

        self.assertEqual(payment.receiver_address, transfer.address)

        transfer_filter = dict(reference_type=transfer_type, reference_id=transfer.id)

        self.assertIsNotNone(self.treasury.debits.filter(**transfer_filter).last())
        self.assertIsNotNone(self.raiden_account.credits.filter(**transfer_filter).last())
