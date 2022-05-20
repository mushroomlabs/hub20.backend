from django.contrib.auth import get_user_model
from django.db import models

from hub20.apps.ethereum_money.models import Token

User = get_user_model()


class UserPreferences(models.Model):
    user = models.OneToOneField(User, related_name="preferences", on_delete=models.CASCADE)
    tokens = models.ManyToManyField(Token)


__all__ = ["UserPreferences"]
