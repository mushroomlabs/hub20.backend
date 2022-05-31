import logging
import threading

from django.core.management.base import BaseCommand

from hub20.apps.core.models import PaymentNetworkProvider

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs all active PaymentNetworkProviders"

    def handle(self, *args, **options):
        try:
            threads = []
            for provider in PaymentNetworkProvider.active.all().select_subclasses():
                logger.info(f"Starting {provider}")
                t = threading.Thread(target=provider.run)
                threads.append(t)
                t.start()
        except KeyboardInterrupt:
            pass
