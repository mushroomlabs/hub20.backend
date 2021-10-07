import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from hub20.apps.blockchain.client import make_web3
from hub20.apps.core.settings import app_settings
from hub20.apps.raiden.client.node import RaidenClient

from .utils import add_shutdown_handlers

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs all defined event handlers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--web3",
            action="extend",
            type=str,
            dest="web3_handlers",
            nargs="*",
        )

        parser.add_argument(
            "--raiden",
            action="extend",
            type=str,
            dest="raiden_handlers",
            nargs="*",
        )

    def handle(self, *args, **options):
        loop = asyncio.get_event_loop()

        add_shutdown_handlers(loop)

        custom_handlers = any((bool(options["web3_handlers"]), bool(options["raiden_handlers"])))

        if custom_handlers:
            web3_listener_modules = options["web3_handlers"] or []
            raiden_listener_modules = options["raiden_handlers"] or []
        else:
            web3_listener_modules = app_settings.Web3.event_listeners
            raiden_listener_modules = app_settings.Raiden.event_listeners

        try:
            tasks = []

            for listener_dotted_name in set(web3_listener_modules):
                try:
                    listener = import_string(listener_dotted_name)
                    w3 = make_web3(settings.WEB3_PROVIDER_URI)
                    tasks.append(listener(w3=w3))
                except ImportError as exc:
                    logger.exception(f"Failed to import {listener_dotted_name}: {exc}")

            for listener_dotted_name in set(raiden_listener_modules):
                try:
                    listener = import_string(listener_dotted_name)

                    for raiden_url in settings.HUB20_RAIDEN_SERVERS:
                        raiden_client = RaidenClient.make(url=raiden_url)
                        w3 = make_web3(settings.WEB3_PROVIDER_URI)
                        tasks.append(listener(w3=w3, raiden_client=raiden_client))
                except ImportError as exc:
                    logger.exception(f"Failed to import {listener_dotted_name}: {exc}")
                except Exception as exc:
                    logger.warning(f"Failed to get raiden client at {raiden_url}: {exc}")

            asyncio.gather(*tasks)
            loop.run_forever()
        finally:
            loop.close()
