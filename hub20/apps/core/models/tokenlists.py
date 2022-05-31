from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from taggit.models import GenericUUIDTaggedItemBase, TaggedItemBase

from ..fields import TokenlistStandardURLField
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


class UserTokenList(AbstractTokenListModel, TimeStampedModel):
    """
    User-defined token lists
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


__all__ = ["TokenList", "UserTokenList"]
