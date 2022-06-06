import logging
import threading
import time

from django.core.management.base import BaseCommand

from hub20.apps.core.models import PaymentRoute

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Listen to different payment providers, checking for payments in open routes"

    def handle(self, *args, **options):
        try:
            route_types = PaymentRoute.__subclasses__()
            PROCESSING_THREADS = {}
            while True:
                PROCESSING_THREADS = {r: t for r, t in PROCESSING_THREADS.items() if t.is_alive()}
                for route_type in route_types:
                    for route in route_type.objects.open():
                        if route.id not in PROCESSING_THREADS:
                            logger.info(f"Processing payments for route {route}")
                            thread = threading.Thread(target=route.process, daemon=True)
                            PROCESSING_THREADS[route.id] = thread
                            thread.start()

                time.sleep(1)

        except KeyboardInterrupt:
            pass
