import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from hub20.apps.blockchain.client import make_web3
from hub20.apps.core.settings import app_settings
from hub20.apps.raiden.client.node import RaidenClient
from hub20.apps.raiden.models import Raiden

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

        listener_modules = options["handlers"] or app_settings.Hub.event_listeners

        try:
            tasks = []

            raiden_account = Raiden.get()

            for listener_dotted_name in set(listener_modules):
                listener = import_string(listener_dotted_name)
                w3 = make_web3(settings.WEB3_PROVIDER_URI)
                raiden = RaidenClient(account=raiden_account)
                tasks.append(listener(w3=w3, raiden=raiden))

            asyncio.gather(*tasks)
            loop.run_forever()
        except ImportError as exc:
            logger.exception(f"Failed to import {listener_modules}: {exc}")
        finally:
            loop.close()
