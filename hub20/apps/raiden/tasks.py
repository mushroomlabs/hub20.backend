import logging

from celery import shared_task

from hub20.apps.raiden.client import RaidenClient
from hub20.apps.raiden.exceptions import RaidenConnectionError
from hub20.apps.raiden.models import Raiden

logger = logging.getLogger(__name__)


@shared_task
def sync_channels():
    for raiden_client in [RaidenClient(raiden_node=raiden) for raiden in Raiden.objects.all()]:
        try:
            logger.debug(f"Running channel sync for {raiden_client.raiden.url}")
            raiden_client.get_channels()
        except RaidenConnectionError as exc:
            logger.error(f"Failed to connect to raiden node: {exc}")
        except Exception as exc:
            logger.exception(f"Error on channel sync: {exc}")


@shared_task
def sync_payments():
    for raiden_client in [RaidenClient(raiden_node=raiden) for raiden in Raiden.objects.all()]:
        try:
            logger.debug(f"Running payment sync for {raiden_client.raiden.url}")
            raiden_client.get_new_payments()
        except RaidenConnectionError as exc:
            logger.error(f"Failed to connect to raiden node: {exc}")
        except Exception as exc:
            logger.exception(f"Error on payment sync: {exc}")
