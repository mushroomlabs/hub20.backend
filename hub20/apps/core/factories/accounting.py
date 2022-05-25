import factory
from django.contrib.contenttypes.models import ContentType

from hub20.apps.core import models

from .users import UserFactory


class UserAccountFactory(factory.django.DjangoModelFactory):
    user = factory.SubFactory(UserFactory)

    class Meta:
        model = models.UserAccount
        django_get_or_create = ("user",)


class UserBookFactory(factory.django.DjangoModelFactory):
    owner_id = factory.SelfAttribute("owner.id")
    owner_type = factory.LazyAttribute(lambda o: ContentType.objects.get_for_model(o.owner))
    owner = factory.SubFactory(UserAccountFactory)

    class Meta:
        model = models.Book


__all__ = [
    "UserAccountFactory",
    "UserBookFactory",
]
