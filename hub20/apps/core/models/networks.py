from django.db import models
from model_utils.managers import InheritanceManager, QueryManager


class BaseProvider(models.Model):
    is_active = models.BooleanField(default=True)
    synced = models.BooleanField(default=False)
    connected = models.BooleanField(default=False)

    objects = InheritanceManager()
    active = QueryManager(is_active=True)
    available = QueryManager(synced=True, connected=True, is_active=True)

    @property
    def is_online(self):
        return self.connected and self.synced


__all__ = ["BaseProvider"]
