import logging

from django.core.management.base import BaseCommand
from django.db import IntegrityError

from hub20.apps.blockchain.client import get_web3
from hub20.apps.blockchain.models import Chain, Web3Provider

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Saves a new blockchain into the database"

    def add_arguments(self, parser):
        parser.add_argument("--id", dest="chain_id", required=True, type=int)
        parser.add_argument("--name", dest="name", required=True, type=str)
        parser.add_argument("--provider-url", dest="provider", required=False, type=str)

    def handle(self, *args, **options):
        chain_id = options["chain_id"]
        name = options["name"]
        try:
            Chain.objects.create(id=chain_id, name=name, highest_block=0)
        except IntegrityError:
            logger.warning(f"Chain {chain_id} already exists. Aborting...")
            return

        provider_url = options["provider"]
        if provider_url:
            w3 = get_web3(provider_url=provider_url)

            if w3.eth.chain_id != chain_id:
                logger.warning(
                    f"Provider reported chain #{w3.eth.chain_id}, expected {chain_id}. Skipping..."
                )
            else:
                provider, _ = Web3Provider.objects.get_or_create(
                    chain_id=chain_id, url=provider_url
                )
                provider.activate()
