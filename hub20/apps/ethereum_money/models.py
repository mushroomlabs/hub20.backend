from __future__ import annotations

import json
import logging
import uuid

import requests
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q, Sum
from django.utils.translation import gettext_lazy as _
from model_utils.managers import QueryManager
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from taggit.models import GenericUUIDTaggedItemBase, TaggedItemBase

from hub20.apps.blockchain.fields import EthereumAddressField
from hub20.apps.blockchain.models import Chain, Transaction

from . import choices
from .fields import EthereumTokenAmountField, TokenlistStandardURLField
from .schemas import TokenList as TokenListDataModel, validate_token_list
from .typing import TokenAmount, TokenAmount_T, Wei

logger = logging.getLogger(__name__)
User = get_user_model()


class UUIDTaggedItem(GenericUUIDTaggedItemBase, TaggedItemBase):
    class Meta:
        verbose_name = _("Tag")
        verbose_name_plural = _("Tags")


class EthereumToken(models.Model):
    NULL_ADDRESS = "0x0000000000000000000000000000000000000000"
    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="tokens")
    address = EthereumAddressField(default=NULL_ADDRESS)
    symbol = models.CharField(max_length=20)
    name = models.CharField(max_length=500)
    decimals = models.PositiveIntegerField(default=18)
    logoURI = TokenlistStandardURLField(max_length=512, null=True, blank=True)
    is_listed = models.BooleanField(default=False)

    objects = models.Manager()
    native = QueryManager(address=NULL_ADDRESS)
    ERC20tokens = QueryManager(~Q(address=NULL_ADDRESS))
    tradeable = QueryManager(chain__providers__is_active=True)
    listed = QueryManager(is_listed=True)

    @property
    def is_ERC20(self) -> bool:
        return self.address != self.NULL_ADDRESS

    @property
    def wrapped_by(self):
        return self.__class__.objects.filter(id__in=self.wrapping_tokens.values("wrapper"))

    @property
    def wraps(self):
        wrapping = getattr(self, "wrappedtoken", None)
        return wrapping and wrapping.wrapper

    @property
    def is_stable(self):
        return hasattr(self, "stable_pair")

    @property
    def tracks_currency(self):
        pairing = getattr(self, "stable_pair", None)
        return pairing and pairing.currency

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
                is_listed=True,
                name=chain.native_token.name,
                decimals=chain.native_token.decimals,
                symbol=chain.native_token.symbol,
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
        EthereumToken, related_name="wrapping_tokens", on_delete=models.CASCADE
    )
    wrapper = models.OneToOneField(EthereumToken, on_delete=models.CASCADE)

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

    token = models.OneToOneField(
        EthereumToken, related_name="stable_pair", on_delete=models.CASCADE
    )
    algorithmic_peg = models.BooleanField(default=True)
    currency = models.CharField(max_length=3, choices=choices.CURRENCIES)


class AbstractTokenListModel(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    name = models.CharField(max_length=64)
    description = models.TextField(null=True)
    tokens = models.ManyToManyField(
        EthereumToken, related_name="%(app_label)s_%(class)s_tokenlists"
    )
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


class TokenList(AbstractTokenListModel):
    """
    A model to manage [token lists](https://tokenlists.org). Only
    admins can manage/import/export them.
    """

    url = TokenlistStandardURLField()
    version = models.CharField(max_length=32)

    class Meta:
        unique_together = ("url", "version")

    @classmethod
    def make(cls, url, token_list_data: TokenListDataModel, description=None):

        token_list, _ = cls.objects.get_or_create(
            url=url,
            version=token_list_data.version.as_string,
            defaults=dict(name=token_list_data.name),
        )
        token_list.description = description
        token_list.keywords.add(*token_list_data.keywords)
        token_list.save()

        for token_entry in token_list_data.tokens:
            token, _ = EthereumToken.objects.get_or_create(
                chain_id=token_entry.chainId,
                address=token_entry.address,
                defaults=dict(
                    name=token_entry.name,
                    decimals=token_entry.decimals,
                    symbol=token_entry.symbol,
                    logoURI=token_entry.logoURI,
                ),
            )
            token_list.tokens.add(token)
        return token_list


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


class TransferEvent(EthereumTokenValueModel):
    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="transfers"
    )
    sender = EthereumAddressField()
    recipient = EthereumAddressField()
    log_index = models.SmallIntegerField(null=True)

    class Meta:
        unique_together = ("transaction", "log_index")
        ordering = ("transaction", "log_index")


__all__ = [
    "EthereumToken",
    "EthereumTokenAmount",
    "EthereumTokenValueModel",
    "StableTokenPair",
    "TokenList",
    "TransferEvent",
    "UserTokenList",
    "WrappedToken",
]
