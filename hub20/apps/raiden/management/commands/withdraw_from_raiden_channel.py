import logging
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand

from hub20.apps.raiden.models import Channel
from hub20.apps.raiden.tasks import make_channel_withdraw

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Calls Raiden node to execute channel withdrawal"

    def add_arguments(self, parser):
        parser.add_argument("-r", "--raiden", required=True, type=str)
        parser.add_argument("-c", "--channel", required=True, type=str)
        parser.add_argument("-a", "--amount", required=True, type=Decimal)

    def handle(self, *args, **options):

        try:
            raiden_url = options["raiden"]
            channel_identifier = options["channel"]
            channel = Channel.objects.get(
                raiden__url=raiden_url, identifier=channel_identifier, status=Channel.STATUS.opened
            )
        except Channel.DoesNotExist:
            logger.info(f"No open channel {channel_identifier} at {raiden_url}")
            sys.exit(-1)

        return make_channel_withdraw(channel_id=channel.id, deposit_amount=options["amount"])
