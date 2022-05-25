from django.contrib.auth import get_user_model
from django.db import models

from .tokens import BaseToken

User = get_user_model()


class UserPreferences(models.Model):
    user = models.OneToOneField(User, related_name="preferences", on_delete=models.CASCADE)
    tokens = models.ManyToManyField(BaseToken)


__all__ = ["UserPreferences"]
