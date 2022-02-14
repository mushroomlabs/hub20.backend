import logging

from django.core.management.base import BaseCommand

from hub20.apps.blockchain.models import Chain
from hub20.apps.raiden.client.node import RaidenClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Saves a new blockchain into the database"

    def add_arguments(self, parser):
        parser.add_argument("-r", "--raiden", dest="raiden_url", required=True, type=str)
        parser.add_argument("-c", "--chain-id", dest="chain_id", required=True, type=int)

    def handle(self, *args, **options):
        chain_id = options["chain_id"]
        raiden_url = options["raiden_url"]

        try:
            chain = Chain.objects.get(id=chain_id, providers__is_active=True)
            RaidenClient.make_raiden(url=raiden_url, chain=chain)
        except Chain.DoesNotExist:
            logger.warn(f"Chain {chain_id} is not active, raiden will not be registered")
