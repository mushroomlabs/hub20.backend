import logging
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand
from django_celery_results.models import TaskResult

from hub20.apps.blockchain.client import make_web3
from hub20.apps.raiden.client import get_service_token
from hub20.apps.raiden.models import Raiden, UserDepositContractOrder
from hub20.apps.raiden.tasks import make_udc_deposit

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Deposits RDN at UserDeposit Contract"

    def add_arguments(self, parser):
        parser.add_argument("-r", "--raiden", required=True, type=str)
        parser.add_argument("-a", "--amount", required=True, type=Decimal)

    def handle(self, *args, **options):

        try:
            raiden_url = options["raiden"]
            raiden = Raiden.objects.get(url=raiden_url)
        except Raiden.DoesNotExist:
            logger.info(f"No raiden defined at {raiden_url}")
            sys.exit(-1)

        w3 = make_web3(provider=raiden.chain.provider)
        rdn = get_service_token(w3=w3)
        deposit_amount = options["amount"]

        if UserDepositContractOrder.objects.filter(task_result__status="PENDING").exists():
            logger.info("Already has pending UDC tasks. Wait or mark them as failed")
            return

        task = make_udc_deposit.delay(raiden_url=raiden_url, amount=deposit_amount)

        result = TaskResult.objects.get_task(task.id)
        result.save()

        UserDepositContractOrder.objects.create(
            raiden=raiden,
            amount=deposit_amount,
            currency=rdn,
            task_result=result,
        )
