import logging

from django.core.management.base import BaseCommand

from hub20.apps.ethereum.models.tokens import Erc20Token

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads token lists (https://tokenlists.org/) according to the schema"

    def add_arguments(self, parser):
        parser.add_argument("urls", metavar="N", nargs="+", type=str)

    def handle(self, *args, **options):

        for url in options["urls"]:
            try:
                Erc20Token.load_tokenlist(url)
            except Exception as exc:
                logger.info(f"Failed to make list from {url}: {exc}")
