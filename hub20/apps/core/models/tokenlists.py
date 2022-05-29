from __future__ import annotations

import json
import logging

import requests
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from taggit.models import GenericUUIDTaggedItemBase, TaggedItemBase

from ..fields import TokenlistStandardURLField
from ..schemas import TokenList as TokenListDataModel, validate_token_list
from .base import BaseModel
from .tokens import BaseToken

logger = logging.getLogger(__name__)
User = get_user_model()


class UUIDTaggedItem(GenericUUIDTaggedItemBase, TaggedItemBase):
    class Meta:
        verbose_name = _("Tag")
        verbose_name_plural = _("Tags")


class AbstractTokenListModel(BaseModel):
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
            token, _ = BaseToken.objects.get_or_create(
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


__all__ = [
    "TokenList",
    "UserTokenList",
]
