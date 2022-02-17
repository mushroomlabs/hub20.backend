import logging

from django.core.management.base import BaseCommand

from hub20.apps.wallet.tasks import update_all_wallet_balances

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Updates balance records for all listed tokens"

    def handle(self, *args, **options):
        update_all_wallet_balances()
