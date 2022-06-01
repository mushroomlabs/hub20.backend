import logging
import threading
import time

from django.core.management.base import BaseCommand

from hub20.apps.core.models import PaymentNetworkProvider

logger = logging.getLogger(__name__)


def run_sync(provider: PaymentNetworkProvider):
    while True:
        provider.sync()
        time.sleep(provider.sync_interval)


class Command(BaseCommand):
    help = "Runs all active PaymentNetworkProviders"

    def handle(self, *args, **options):
        try:
            SYNCING_THREADS = {}
            while True:
                for provider in PaymentNetworkProvider.active.all().select_subclasses():
                    if provider not in SYNCING_THREADS:
                        logger.info(f"Starting {provider}")
                        thread = threading.Thread(target=run_sync, args=(provider,))
                        SYNCING_THREADS[provider] = thread
                        thread.start()

                time.sleep(5)

        except KeyboardInterrupt:
            pass
