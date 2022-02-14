import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from hub20.apps.core.models import UserAccount, UserPreferences

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = """
    Ensures all user and wallet-related models are created.
    Useful for development only, when migrations destroy the
    UserAccount, Profile and Settings
    """

    def handle(self, *args, **options):
        for user in User.objects.all():
            UserAccount.objects.get_or_create(user=user)
            UserPreferences.objects.get_or_create(user=user)
