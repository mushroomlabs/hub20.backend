import logging
import sys

from django.core.management.base import BaseCommand

from hub20.apps.ethereum.models import Chain, Erc20Token, Web3Provider

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Gets information about a token from the blockchain and lists it"

    def add_arguments(self, parser):
        parser.add_argument("--chain-id", "-c", dest="chain_id", required=True, type=int)
        parser.add_argument("--address", "-a", dest="address", required=True, type=str)
        parser.add_argument("--listed", action="store_true")

    def handle(self, *args, **options):

        try:
            chain_id = options["chain_id"]
            chain = Chain.objects.get(id=chain_id)
            provider = Web3Provider.active.get(network__blockchainpaymentnetwork__chain=chain)
        except Chain.DoesNotExist:
            logger.error(f"Chain {chain_id} not found.")
            sys.exit(-1)
        except Web3Provider.DoesNotExist:
            logger.error("No web3 provider for {chain.name}")
            sys.exit(-1)

        token_address = options["address"]
        logger.info(f"Checking token {token_address}...")
        try:
            token: Erc20Token = provider.save_token(token_address=token_address)
            if options["listed"]:
                token.is_listed = True
                token.save()
        except OverflowError:
            logger.error(f"{token_address} is not a valid address or not ERC20-compliant")
        except Exception:
            logger.exception(f"Failed to load token data for {token_address}")
