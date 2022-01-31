import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)
User = get_user_model()

from hub20.apps.core.models import UserPreferences


@receiver(post_save, sender=User)
def on_user_created_create_user_preferences(sender, **kw):
    if kw["created"]:
        UserPreferences.objects.get_or_create(user=kw["instance"])


__all__ = ["on_user_created_create_user_preferences"]
