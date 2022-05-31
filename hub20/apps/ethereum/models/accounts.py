import functools
import logging
import os
from typing import Optional

import ethereum
from django.db import models
from django.db.models import Max, Q
from hdwallet import HDWallet
from hdwallet.symbols import ETH
from model_utils.managers import InheritanceManager

from hub20.apps.core.fields import EthereumAddressField, HexField
from hub20.apps.core.models import TokenValueModel
from hub20.apps.core.settings import app_settings

from .blockchain import Block, Transaction

logger = logging.getLogger(__name__)


class BaseWallet(models.Model):
    address = EthereumAddressField(unique=True, db_index=True, blank=False)
    transactions = models.ManyToManyField(Transaction)
    objects = InheritanceManager()

    def historical_balance(self, token):
        return self.balance_records.filter(currency=token).order_by("block__number")

    def current_balance(self, token):
        return self.historical_balance(token).last()

    @property
    def balances(self):
        # There has to be a better way to convert a ValuesQuerySet
        # into a Queryset, but for the moment it will be okay.
        record_qs = self.balance_records.values("currency").annotate(
            block__number=Max("block__number")
        )

        filter_q = functools.reduce(lambda x, y: x | y, [Q(**r) for r in record_qs])

        return self.balance_records.filter(amount__gt=0).filter(filter_q)

    @property
    def private_key_bytes(self) -> Optional[bytes]:
        private_key = getattr(self, "private_key", None)
        return private_key and bytearray.fromhex(private_key[2:])

    def __str__(self):
        return self.address


class WalletBalanceRecord(TokenValueModel):
    """
    Provides a blocktime-series record of balances for any account
    """

    wallet = models.ForeignKey(
        BaseWallet, related_name="balance_records", on_delete=models.CASCADE
    )
    block = models.ForeignKey(Block, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("wallet", "currency", "block")


class ColdWallet(BaseWallet):
    @classmethod
    def generate(cls):
        raise TypeError("Cold wallets do not store private keys and can not be generated")


class KeystoreAccount(BaseWallet):
    private_key = HexField(max_length=64, unique=True)

    @classmethod
    def generate(cls):
        private_key = os.urandom(32)
        address = ethereum.utils.privtoaddr(private_key)
        checksum_address = ethereum.utils.checksum_encode(address.hex())
        return cls.objects.create(address=checksum_address, private_key=private_key.hex())


class HierarchicalDeterministicWallet(BaseWallet):
    BASE_PATH_FORMAT = "m/44'/60'/0'/0/{index}"

    index = models.PositiveIntegerField(unique=True)

    @property
    def private_key(self):
        wallet = self.__class__.get_wallet(index=self.index)
        return wallet.private_key()

    @property
    def private_key_bytes(self) -> bytes:
        return bytearray.fromhex(self.private_key)

    @classmethod
    def get_wallet(cls, index: int) -> HDWallet:
        wallet = HDWallet(symbol=ETH)

        if app_settings.Wallet.mnemonic:
            wallet.from_mnemonic(mnemonic=app_settings.Wallet.mnemonic)
        elif app_settings.Wallet.root_key:
            wallet.from_xprivate_key(xprivate_key=app_settings.Wallet.root_key)
        else:
            raise ValueError("Can not generate new addresses for HD Wallets. No seed available")

        wallet.from_path(cls.BASE_PATH_FORMAT.format(index=index))
        return wallet

    @classmethod
    def generate(cls):
        latest_generation = cls.get_latest_generation()
        index = 0 if latest_generation is None else latest_generation + 1
        wallet = HierarchicalDeterministicWallet.get_wallet(index)
        return cls.objects.create(index=index, address=wallet.p2pkh_address())

    @classmethod
    def get_latest_generation(cls) -> Optional[int]:
        return cls.objects.aggregate(generation=Max("index")).get("generation")


__all__ = [
    "BaseWallet",
    "ColdWallet",
    "KeystoreAccount",
    "HierarchicalDeterministicWallet",
    "WalletBalanceRecord",
]
