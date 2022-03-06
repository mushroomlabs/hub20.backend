import logging

from django.core.management.base import BaseCommand

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import Chain, Web3Provider
from hub20.apps.raiden.client import (
    RaidenClient,
    get_service_deposit_balance,
    get_service_token,
    get_service_total_deposit,
)
from hub20.apps.raiden.models import UserDeposit

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Saves a new raiden into"

    def add_arguments(self, parser):
        parser.add_argument("-r", "--raiden", dest="raiden_url", required=True, type=str)
        parser.add_argument("-c", "--chain-id", dest="chain_id", required=True, type=int)

    def handle(self, *args, **options):
        chain_id = options["chain_id"]
        raiden_url = options["raiden_url"]

        try:
            chain = Chain.objects.get(id=chain_id, providers__is_active=True)
            raiden = RaidenClient.make_raiden(url=raiden_url, chain=chain)
            provider = Web3Provider.available.get(chain=chain)
            w3 = make_web3(provider=provider)
            service_token = get_service_token(w3=w3)
            total_deposit = get_service_total_deposit(w3=w3, raiden=raiden)
            balance = get_service_deposit_balance(w3=w3, raiden=raiden)

            UserDeposit.objects.create(
                raiden=raiden,
                token=service_token,
                total_deposit=total_deposit.amount,
                balance=balance.amount,
            )

        except Chain.DoesNotExist:
            logger.warn(f"Chain {chain_id} is not active, raiden will not be registered")

        except Web3Provider.DoesNotExist:
            logger.warn(
                f"No Web3 provider available on {chain_id}, raiden info will not be recorded"
            )
