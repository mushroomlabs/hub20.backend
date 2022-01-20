import asyncio
import logging

from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from hub20.apps.blockchain.client import event_streams as blockchain_streams
from hub20.apps.ethereum_money.client import event_streams as token_event_streams
from hub20.apps.raiden.client import event_streams as raiden_event_streams
from hub20.apps.raiden.client.node import sync_channels, sync_payments

from .utils import add_shutdown_handlers

logger = logging.getLogger(__name__)


BLOCKCHAIN_STREAMS = [
    blockchain_streams.process_mined_blocks,
    blockchain_streams.process_pending_transactions,
    token_event_streams.process_token_transfer_events,
    token_event_streams.process_pending_token_transfers,
    raiden_event_streams.process_channel_events,
]

INTEGRATION_STREAMS = []

RAIDEN_STREAMS = [sync_channels, sync_payments]


class Command(BaseCommand):
    help = "Runs all functions that stream events from web3 and raiden nodes"

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

        all_streams = BLOCKCHAIN_STREAMS + INTEGRATION_STREAMS + RAIDEN_STREAMS

        streams = options["streams"] or all_streams

        try:
            tasks = []

            for stream in streams:
                tasks.append(stream())

            asyncio.gather(*tasks, return_exceptions=True)
            loop.run_forever()
        finally:
            loop.close()
