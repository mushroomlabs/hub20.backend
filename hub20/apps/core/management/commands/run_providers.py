import logging
import threading
import time

from django.core.management.base import BaseCommand

from hub20.apps.core.models import PaymentNetworkProvider

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run all network providers"

    def handle(self, *args, **options):
        try:
            PROCESSING_THREADS = {}
            while True:
                PROCESSING_THREADS = {r: t for r, t in PROCESSING_THREADS.items() if t.is_alive()}
                for provider in PaymentNetworkProvider.active.select_subclasses():
                    if provider.id not in PROCESSING_THREADS:
                        logger.info(f"Starting provider {provider}")
                        thread = threading.Thread(target=provider.run, daemon=True)
                        PROCESSING_THREADS[provider.id] = thread
                        thread.start()
                time.sleep(1)

        except KeyboardInterrupt:
            pass
