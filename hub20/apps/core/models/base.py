import uuid

from django.db import models


class BaseModel(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)

    class Meta:
        abstract = True


class PolymorphicModelMixin:
    @property
    def subclassed(self):
        return self.__class__.objects.get_subclass(id=self.id)
