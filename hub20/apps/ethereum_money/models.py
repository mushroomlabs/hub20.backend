from __future__ import annotations

import logging
import os
from typing import Any, Optional

import ethereum
from django.conf import settings
from django.db import models
from django.db.models import Max, Q, Sum
from hdwallet import HDWallet
from hdwallet.symbols import ETH
from model_utils.managers import QueryManager
from web3 import Web3
from web3.contract import Contract

from hub20.apps.blockchain.fields import EthereumAddressField, HexField
from hub20.apps.blockchain.models import BaseEthereumAccount, Chain

from .abi import EIP20_ABI
from .app_settings import HD_WALLET_MNEMONIC, HD_WALLET_ROOT_KEY
from .typing import TokenAmount, TokenAmount_T, Wei

logger = logging.getLogger(__name__)


class EthereumToken(models.Model):
    NULL_ADDRESS = "0x0000000000000000000000000000000000000000"
    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="tokens")
    code = models.CharField(max_length=8)
    name = models.CharField(max_length=500)
    decimals = models.PositiveIntegerField(default=18)
    address = EthereumAddressField(default=NULL_ADDRESS)
    is_listed = models.BooleanField(default=False)

    objects = models.Manager()
    ERC20tokens = QueryManager(
        ~Q(address=NULL_ADDRESS) & Q(chain_id=settings.BLOCKCHAIN_NETWORK_ID)
    )
    tracked = QueryManager(is_listed=True, chain_id=settings.BLOCKCHAIN_NETWORK_ID)
    ethereum = QueryManager(address=NULL_ADDRESS, chain_id=settings.BLOCKCHAIN_NETWORK_ID)

    @property
    def is_ERC20(self) -> bool:
        return self.address != self.NULL_ADDRESS

    def __str__(self) -> str:
        components = [self.code]
        if self.is_ERC20:
            components.append(self.address)

        components.append(str(self.chain_id))
        return " - ".join(components)

    def get_contract(self, w3: Web3) -> Contract:
        if not self.is_ERC20:
            raise ValueError("Not an ERC20 token")

        return w3.eth.contract(abi=EIP20_ABI, address=self.address)

    def from_wei(self, wei_amount: Wei) -> EthereumTokenAmount:
        value = TokenAmount(wei_amount) / (10 ** self.decimals)
        return EthereumTokenAmount(amount=value, currency=self)

    @staticmethod
    def ETH(chain: Chain):
        eth, _ = EthereumToken.objects.update_or_create(
            chain=chain,
            code="ETH",
            address=EthereumToken.NULL_ADDRESS,
            defaults={"is_listed": True, "name": "Ethereum"},
        )
        return eth

    @classmethod
    def make(cls, address: str, chain: Chain, **defaults):
        if address == EthereumToken.NULL_ADDRESS:
            return EthereumToken.ETH(chain)

        obj, _ = cls.objects.update_or_create(address=address, chain=chain, defaults=defaults)
        return obj

    class Meta:
        unique_together = (("chain", "address"),)


class EthereumTokenAmountField(models.DecimalField):
    def __init__(self, *args: Any, **kw: Any) -> None:
        kw.setdefault("decimal_places", 18)
        kw.setdefault("max_digits", 32)

        super().__init__(*args, **kw)


class EthereumTokenValueModel(models.Model):
    amount = EthereumTokenAmountField()
    currency = models.ForeignKey(EthereumToken, on_delete=models.PROTECT)

    @property
    def as_token_amount(self):
        return EthereumTokenAmount(amount=self.amount, currency=self.currency)

    @property
    def formatted_amount(self):
        return self.as_token_amount.formatted

    class Meta:
        abstract = True


class ColdWallet(BaseEthereumAccount):
    @classmethod
    def generate(cls):
        raise TypeError("Cold wallets do not store private keys and can not be generated")


class KeystoreAccount(BaseEthereumAccount):
    private_key = HexField(max_length=64, unique=True)

    @classmethod
    def generate(cls):
        private_key = os.urandom(32)
        address = ethereum.utils.privtoaddr(private_key)
        checksum_address = ethereum.utils.checksum_encode(address.hex())
        return cls.objects.create(address=checksum_address, private_key=private_key.hex())


class HierarchicalDeterministicWallet(BaseEthereumAccount):
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

        if HD_WALLET_MNEMONIC:
            wallet.from_mnemonic(mnemonic=HD_WALLET_MNEMONIC)
        elif HD_WALLET_ROOT_KEY:
            wallet.from_root_xprivate_key(xprivate_key=HD_WALLET_ROOT_KEY)
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


class EthereumTokenAmount:
    def __init__(self, amount: TokenAmount_T, currency: EthereumToken):
        self.amount: TokenAmount = TokenAmount(amount)
        self.currency: EthereumToken = currency

    @property
    def formatted(self):
        integral = int(self.amount)
        frac = self.amount % 1

        amount_formatted = str(integral) if not bool(frac) else self.amount.normalize()
        return f"{amount_formatted} {self.currency.code}"

    @property
    def as_wei(self) -> Wei:
        return Wei(self.amount * (10 ** self.currency.decimals))

    @property
    def as_hex(self) -> str:
        return hex(self.as_wei)

    @property
    def is_ETH(self) -> bool:
        return self.currency.address == EthereumToken.NULL_ADDRESS

    def _check_currency_type(self, other: EthereumTokenAmount):
        if not self.currency == other.currency:
            raise ValueError(f"Can not operate {self.currency} and {other.currency}")

    def __add__(self, other: EthereumTokenAmount) -> EthereumTokenAmount:
        self._check_currency_type(self)
        return self.__class__(self.amount + other.amount, self.currency)

    def __sub__(self, other: EthereumTokenAmount) -> EthereumTokenAmount:
        self._check_currency_type(self)
        return self.__class__(self.amount - other.amount, self.currency)

    def __mul__(self, other: TokenAmount_T) -> EthereumTokenAmount:
        return EthereumTokenAmount(amount=TokenAmount(other * self.amount), currency=self.currency)

    def __rmul__(self, other: TokenAmount_T) -> EthereumTokenAmount:
        return self.__mul__(other)

    def __eq__(self, other: object) -> bool:
        message = f"Can not compare {self.currency} amount with {type(other)}"
        assert isinstance(other, EthereumTokenAmount), message

        return self.currency == other.currency and self.amount == other.amount

    def __lt__(self, other: EthereumTokenAmount):
        self._check_currency_type(other)
        return self.amount < other.amount

    def __le__(self, other: EthereumTokenAmount):
        self._check_currency_type(other)
        return self.amount <= other.amount

    def __gt__(self, other: EthereumTokenAmount):
        self._check_currency_type(other)
        return self.amount > other.amount

    def __ge__(self, other: EthereumTokenAmount):
        self._check_currency_type(other)
        return self.amount >= other.amount

    def __str__(self):
        return self.formatted

    def __repr__(self):
        return self.formatted

    @classmethod
    def aggregated(cls, queryset, currency: EthereumToken):
        entries = queryset.filter(currency=currency)
        amount = entries.aggregate(total=Sum("amount")).get("total") or TokenAmount(0)
        return cls(amount=amount, currency=currency)


__all__ = [
    "EthereumToken",
    "EthereumTokenAmount",
    "EthereumTokenValueModel",
    "ColdWallet",
    "KeystoreAccount",
    "HierarchicalDeterministicWallet",
]
