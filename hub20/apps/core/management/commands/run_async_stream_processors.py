import asyncio
import logging

from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from .utils import add_shutdown_handlers

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Collects and runs async based stream processors in one single event loop"

    def add_arguments(self, parser):
        parser.add_argument(
            "--stream",
            action="extend",
            type=import_string,
            dest="streams",
            nargs="*",
        )

    def handle(self, *args, **options):
        loop = asyncio.get_event_loop()

        add_shutdown_handlers(loop)

        try:
            tasks = []

            for stream in options["streams"]:
                tasks.append(stream())

            asyncio.gather(*tasks, return_exceptions=True)
            loop.run_forever()
        finally:
            loop.close()
