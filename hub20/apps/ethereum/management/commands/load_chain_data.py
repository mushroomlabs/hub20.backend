import logging

import requests
from django.core.management.base import BaseCommand
from django.template.defaultfilters import slugify

from hub20.apps.ethereum import models
from hub20.apps.ethereum.schemas import chainlist

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Loads all chain information according to chainlist schema"

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            dest="url",
            default="https://chainid.network/chains.json",
        )

    def handle(self, *args, **options):

        response = requests.get(options["url"])
        response.raise_for_status()

        for entry in response.json():
            try:
                chain_data = chainlist.Chain(**entry)
                chain, _ = models.Chain.objects.get_or_create(
                    id=chain_data.chainId,
                    defaults=dict(
                        name=chain_data.name,
                        highest_block=0,
                    ),
                )

                models.ChainMetadata.objects.update_or_create(
                    chain=chain, defaults={"short_name": slugify(chain_data.shortName)}
                )

                native_token_data = chain_data.nativeCurrency
                models.NativeToken.objects.update_or_create(
                    chain=chain, defaults=native_token_data.dict()
                )

                for provider_url in chain_data.rpc:
                    models.Web3Provider.objects.get_or_create(
                        network=chain.blockchainpaymentnetwork,
                        url=provider_url,
                        defaults=dict(is_active=False),
                    )

                blockchain_explorers = chain_data.explorers or []
                for explorer in blockchain_explorers:
                    models.Explorer.objects.get_or_create(chain=chain, defaults=explorer.dict())
            except Exception as exc:
                logger.exception(exc)
