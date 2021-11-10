from django.core.management.base import BaseCommand

from hub20.apps.blockchain.client import download_all_chain, get_web3


class Command(BaseCommand):
    help = "Downloads all blocks from ethereum client and save the data on the database"

    def handle(self, *args, **options):
        w3 = get_web3()

        download_all_chain(w3=w3)
