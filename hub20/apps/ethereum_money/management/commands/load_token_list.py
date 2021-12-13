import logging

import requests
from django.core.management.base import BaseCommand

from hub20.apps.ethereum_money import models
from hub20.apps.ethereum_money.schemas import TokenList, validate_token_list

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads token lists (https://tokenlists.org/) according to the schema"

    def add_arguments(self, parser):
        parser.add_argument("urls", metavar="N", nargs="+", type=str)

    def handle(self, *args, **options):

        for url in options["urls"]:
            response = requests.get(url)
            response.raise_for_status()

            token_list_data = response.json()
            validate_token_list(token_list_data)
            token_list = TokenList(**token_list_data)
            for token in token_list.tokens:
                models.EthereumToken.objects.update_or_create(
                    chain_id=token.chainId,
                    address=token.address,
                    defaults=dict(
                        name=token.name,
                        decimals=token.decimals,
                        symbol=token.symbol,
                        logoURI=token.logoURI,
                    ),
                )
