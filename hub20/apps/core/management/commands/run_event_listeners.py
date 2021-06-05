import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from hub20.apps.blockchain.client import make_web3, sync_chain
from hub20.apps.core.settings import app_settings
from hub20.apps.raiden.client.node import RaidenClient

from .utils import add_shutdown_handlers

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs all defined event handlers"

    def handle(self, *args, **options):
        loop = asyncio.get_event_loop()

        add_shutdown_handlers(loop)

        try:
            tasks = []

            for listener_dotted_name in app_settings.Hub.event_listeners:
                listener = import_string(listener_dotted_name)
                w3 = make_web3(settings.WEB3_PROVIDER_URI)
                raiden = RaidenClient()
                tasks.append(listener(w3=w3, raiden=raiden))

            # No matter the user settings, we always want to run the routine to
            # update the chain status
            tasks.append(sync_chain(w3=make_web3(settings.WEB3_PROVIDER_URI)))

            asyncio.gather(*tasks)
            loop.run_forever()
        finally:
            loop.close()
