from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q, Sum
from model_utils.managers import QueryManager

from hub20.apps.blockchain.fields import EthereumAddressField
from hub20.apps.blockchain.models import Chain

from .fields import EthereumTokenAmountField, TokenLogoURLField
from .typing import TokenAmount, TokenAmount_T, Wei

logger = logging.getLogger(__name__)
User = get_user_model()


class EthereumToken(models.Model):
    NULL_ADDRESS = "0x0000000000000000000000000000000000000000"
    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="tokens")
    address = EthereumAddressField(default=NULL_ADDRESS)
    symbol = models.CharField(max_length=20)
    name = models.CharField(max_length=500)
    decimals = models.PositiveIntegerField(default=18)
    logoURI = TokenLogoURLField(null=True)
    is_listed = models.BooleanField(default=False)

    objects = models.Manager()
    native = QueryManager(address=NULL_ADDRESS)
    ERC20tokens = QueryManager(~Q(address=NULL_ADDRESS))

    @property
    def is_ERC20(self) -> bool:
        return self.address != self.NULL_ADDRESS

    def __str__(self) -> str:
        components = [self.symbol]
        if self.is_ERC20:
            components.append(self.address)

        components.append(str(self.chain_id))
        return " - ".join(components)

    def from_wei(self, wei_amount: Wei) -> EthereumTokenAmount:
        value = TokenAmount(wei_amount) / (10 ** self.decimals)
        return EthereumTokenAmount(amount=value, currency=self)

    @classmethod
    def make_native(cls, chain: Chain):
        token, _ = cls.objects.update_or_create(
            chain=chain,
            address=cls.NULL_ADDRESS,
            defaults=dict(
                is_listed=True, name=chain.native_token.name, decimals=chain.native_token.decimals
            ),
        )
        return token

    @classmethod
    def make(cls, address: str, chain: Chain, **defaults):
        if address == cls.NULL_ADDRESS:
            return cls.make_native(chain)

        obj, _ = cls.objects.update_or_create(address=address, chain=chain, defaults=defaults)
        return obj

    class Meta:
        unique_together = (("chain", "address"),)


class WrappedToken(models.Model):
    wrapped = models.ForeignKey(
        EthereumToken, related_name="wrapping_tokens", on_delete=models.CASCADE
    )
    wrapper = models.OneToOneField(EthereumToken, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("wrapped", "wrapper")


class UserTokenList(models.Model):
    """
    Eventually we will add methods that allow users to manage their
    own [token lists](https://tokenlists.org)
    """

    created_by = models.ForeignKey(User, related_name="token_lists", on_delete=models.CASCADE)
    name = models.CharField(max_length=64)
    description = models.TextField(null=True)
    tokens = models.ManyToManyField(EthereumToken)

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ("name", "created_by")


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


class EthereumTokenAmount:
    def __init__(self, amount: TokenAmount_T, currency: EthereumToken):
        self.amount: TokenAmount = TokenAmount(amount)
        self.currency: EthereumToken = currency

    @property
    def formatted(self):
        integral = int(self.amount)
        frac = self.amount % 1

        amount_formatted = str(integral) if not bool(frac) else self.amount.normalize()
        return f"{amount_formatted} {self.currency.symbol}"

    @property
    def as_wei(self) -> Wei:
        return Wei(self.amount * (10 ** self.currency.decimals))

    @property
    def as_hex(self) -> str:
        return hex(self.as_wei)

    @property
    def is_native_token(self) -> bool:
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
        return EthereumTokenAmount(amount=TokenAmount(other) * self.amount, currency=self.currency)

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
    "TokenList",
    "WrappedToken",
]
