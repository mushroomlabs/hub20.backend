from django.test import TestCase

from hub20.apps.core.factories import InternalTransferFactory
from hub20.apps.core.models import Transfer, TransferConfirmation


class TransferManagerTestCase(TestCase):
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


__all__ = ["TransferManagerTestCase"]
