import logging

from django.core.management.base import BaseCommand

from hub20.apps.blockchain.client import get_web3, inspect_web3
from hub20.apps.blockchain.models import Chain, Web3Provider

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sets the web3 rpc node used to interact with the blockchain"

    def add_arguments(self, parser):
        parser.add_argument("urls", metavar="N", nargs="+", type=str)

    def handle(self, *args, **options):

        for url in options["urls"]:
            w3 = get_web3(provider_url=url)
            try:
                chain_id = w3.eth.chain_id
                chain = Chain.objects.filter(id=chain_id).first()
                if not chain:
                    logger.warn(
                        f"Node at {url} is connected to network {chain_id}, which we do not know"
                    )
                    continue
                configuration = inspect_web3(w3)
                provider, _ = Web3Provider.objects.update_or_create(
                    chain=chain, url=url, defaults=configuration.dict()
                )
                provider.activate()
            except Exception as exc:
                logger.info(f"Error when connecting to {url}: {exc}")
