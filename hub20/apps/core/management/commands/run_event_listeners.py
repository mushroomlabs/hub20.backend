import asyncio
import logging

from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from hub20.apps.core.settings import app_settings

from .utils import add_shutdown_handlers

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs all defined event handlers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--handler",
            action="extend",
            type=str,
            dest="handlers",
            nargs="*",
        )

    def handle(self, *args, **options):
        loop = asyncio.get_event_loop()

        add_shutdown_handlers(loop)

        all_handlers = app_settings.Web3.event_listeners + app_settings.Raiden.event_listeners

        event_handlers = options["handlers"] or all_handlers

        try:
            tasks = []

            for listener_dotted_name in set(event_handlers):
                try:
                    listener = import_string(listener_dotted_name)
                    tasks.append(listener())
                except ImportError as exc:
                    logger.exception(f"Failed to import {listener_dotted_name}: {exc}")

            asyncio.gather(*tasks)
            loop.run_forever()
        finally:
            loop.close()
