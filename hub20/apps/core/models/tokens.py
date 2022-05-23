from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal

import requests
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q, Sum
from django.utils.translation import gettext_lazy as _
from model_utils.managers import InheritanceManager, QueryManager
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from taggit.models import GenericUUIDTaggedItemBase, TaggedItemBase

from ..choices import CURRENCIES
from ..fields import AddressField, TokenAmountField, TokenlistStandardURLField
from ..schemas import TokenList as TokenListDataModel, validate_token_list
from ..typing import TokenAmount_T, Wei
from .blockchain import Chain

logger = logging.getLogger(__name__)
User = get_user_model()


class UUIDTaggedItem(GenericUUIDTaggedItemBase, TaggedItemBase):
    class Meta:
        verbose_name = _("Tag")
        verbose_name_plural = _("Tags")


class BaseToken(models.Model):
    name = models.CharField(max_length=500)
    symbol = models.CharField(max_length=16)
    decimals = models.PositiveIntegerField(default=18)
    logoURI = TokenlistStandardURLField(max_length=512, null=True, blank=True)
    is_listed = models.BooleanField(default=False)
    objects = InheritanceManager()


class WrappedToken(models.Model):
    """
    Tokens that have are minted and burned dependent on how much
    of a primary token is locked are called 'wrapper tokens'. This can
    happen in-chain (e.g, W-ETH wrapping ETH), or cross-chain
    "bridged" tokens (e.g, WBTC wrapping BTC, Binance BAT wrapping
    ERC20 BAT, Arbitrum DAI wrapping Ethereum DAI, etc)a

    The idea of this table is to provide a way for operators and users
    to optionally accept payments and transfers of a wrapped token
    instead of the 'original' one.

    """

    wrapped = models.ForeignKey(
        BaseToken, related_name="wrapping_tokens", on_delete=models.CASCADE
    )
    wrapper = models.OneToOneField(BaseToken, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("wrapped", "wrapper")


class StableTokenPair(models.Model):
    """
    A stabletoken is a token whose value is supposed to be pegged to a
    'real' fiat currency. These value pegs can be 'soft' or 'hard',
    (e.g, both USDC and DAI are pegged to the USD, but DAI's price is
    determined algorithmically and therefore can oscillate, while USDC
    is supposed to always be worth one USD
    """

    token = models.OneToOneField(BaseToken, related_name="stable_pair", on_delete=models.CASCADE)
    algorithmic_peg = models.BooleanField(default=True)
    currency = models.CharField(max_length=3, choices=CURRENCIES)


class AbstractTokenListModel(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    name = models.CharField(max_length=64)
    description = models.TextField(null=True)
    tokens = models.ManyToManyField(BaseToken, related_name="%(app_label)s_%(class)s_tokenlists")
    keywords = TaggableManager(through=UUIDTaggedItem)

    def __str__(self):
        return self.name

    @classmethod
    def fetch(cls, url) -> TokenListDataModel:
        response = requests.get(url)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            raise ValueError(f"Failed to fetch {url}")

        try:
            token_list_data = response.json()
        except json.decoder.JSONDecodeError:
            raise ValueError(f"Could not decode json response from {url}")

        validate_token_list(token_list_data)

        return TokenListDataModel(**token_list_data)

    class Meta:
        abstract = True


class UserTokenList(AbstractTokenListModel, TimeStampedModel):
    """
    A model to manage [token lists](https://tokenlists.org). Only
    admins can manage/import/export them.
    """

    user = models.ForeignKey(User, related_name="token_lists", on_delete=models.CASCADE)

    @classmethod
    def clone(cls, user, token_list: TokenList):
        user_token_list = user.token_lists.create(
            name=token_list.name,
            description=token_list.description,
        )
        user_token_list.tokens.set(token_list.tokens.all())
        user_token_list.keywords.set(token_list.keywords.all())
        return user_token_list


class TokenValueModel(models.Model):
    amount = TokenAmountField()
    currency = models.ForeignKey(BaseToken, on_delete=models.PROTECT)

    @property
    def as_token_amount(self):
        return TokenAmount(amount=self.amount, currency=self.currency)

    @property
    def formatted_amount(self):
        return self.as_token_amount.formatted

    class Meta:
        abstract = True


class TokenAmount:
    def __init__(self, amount: TokenAmount_T, currency: BaseToken):
        self.amount: Decimal = Decimal(amount)
        self.currency: BaseToken = currency

    @property
    def formatted(self):
        integral = int(self.amount)
        frac = self.amount % 1

        amount_formatted = str(integral) if not bool(frac) else self.amount.normalize()
        return f"{amount_formatted} {self.currency.symbol}"

    @property
    def as_wei(self) -> Wei:
        return Wei(self.amount * (10**self.currency.decimals))

    @property
    def as_hex(self) -> str:
        return hex(self.as_wei)

    def _check_currency_type(self, other: TokenAmount):
        if not self.currency == other.currency:
            raise ValueError(f"Can not operate {self.currency} and {other.currency}")

    def __add__(self, other: TokenAmount) -> TokenAmount:
        self._check_currency_type(self)
        return self.__class__(self.amount + other.amount, self.currency)

    def __sub__(self, other: TokenAmount) -> TokenAmount:
        self._check_currency_type(self)
        return self.__class__(self.amount - other.amount, self.currency)

    def __mul__(self, other: TokenAmount_T) -> TokenAmount:
        return TokenAmount(amount=TokenAmount(other) * self.amount, currency=self.currency)

    def __rmul__(self, other: TokenAmount_T) -> TokenAmount:
        return self.__mul__(other)

    def __eq__(self, other: object) -> bool:
        message = f"Can not compare {self.currency} amount with {type(other)}"
        assert isinstance(other, TokenAmount), message

        return self.currency == other.currency and self.amount == other.amount

    def __lt__(self, other: TokenAmount):
        self._check_currency_type(other)
        return self.amount < other.amount

    def __le__(self, other: TokenAmount):
        self._check_currency_type(other)
        return self.amount <= other.amount

    def __gt__(self, other: TokenAmount):
        self._check_currency_type(other)
        return self.amount > other.amount

    def __ge__(self, other: TokenAmount):
        self._check_currency_type(other)
        return self.amount >= other.amount

    def __str__(self):
        return self.formatted

    def __repr__(self):
        return self.formatted

    @classmethod
    def aggregated(cls, queryset, currency: Token):
        entries = queryset.filter(currency=currency)
        amount = entries.aggregate(total=Sum("amount")).get("total") or TokenAmount(0)
        return cls(amount=amount, currency=currency)


__all__ = [
    "Token",
    "TokenAmount",
    "TokenValueModel",
    "StableTokenPair",
    "TokenList",
    "UserTokenList",
    "WrappedToken",
]
