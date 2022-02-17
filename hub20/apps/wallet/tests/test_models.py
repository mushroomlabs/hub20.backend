import pytest
from django.test import TestCase
from eth_utils import is_checksum_address

from hub20.apps.ethereum_money.factories import Erc20TokenFactory

from ..factories import WalletBalanceRecordFactory, WalletFactory


@pytest.mark.django_db(transaction=True)
class BaseTestCase(TestCase):
    pass


class WalletTestCase(BaseTestCase):
    def setUp(self):
        self.wallet = WalletFactory()

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


__all__ = ["WalletTestCase"]
