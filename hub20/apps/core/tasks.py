import logging

import httpx
from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone

from .consumers import CheckoutConsumer, SessionEventsConsumer
from .models import Checkout, Transfer

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task
def execute_transfer(transfer_id):
    try:
        transfer = Transfer.pending.get(id=transfer_id)
        transfer.execute()
    except Transfer.DoesNotExist:
        logger.warning(f"Transfer {transfer_id} not found or already executed")


@shared_task
def execute_pending_transfers():
    for transfer in Transfer.pending.exclude(execute_on__gt=timezone.now()):
        transfer.execute()


@shared_task
def send_session_event(session_key, event, **event_data):
    layer = get_channel_layer()
    channel_group_name = SessionEventsConsumer.get_group_name(session_key)
    event_data.update({"type": "notify_event", "event": event})
    logger.info(f"Sending session event to {session_key}")
    async_to_sync(layer.group_send)(channel_group_name, event_data)


@shared_task
def publish_checkout_event(checkout_id, event="checkout.event", **event_data):
    layer = get_channel_layer()
    channel_group_name = CheckoutConsumer.get_group_name(checkout_id)

    logger.info(f"Publishing checkout event {event}. Data: {event_data}")

    event_data.update({"type": "checkout_event", "event_name": event})

    async_to_sync(layer.group_send)(channel_group_name, event_data)


@shared_task
def call_checkout_webhook(checkout_id):
    try:
        checkout = Checkout.objects.get(id=checkout_id)
        url = checkout.store.checkout_webhook_url

        if not url:
            logger.info(f"Checkout {checkout_id} does not have a url")
            return

        try:
            voucher_data = checkout.voucher_data
            voucher_data.update(dict(encoded=checkout.store.issue_jwt(**voucher_data)))
            response = httpx.post(url, json=voucher_data)
            response.raise_for_status()
        except httpx.ConnectError:
            logger.warning(f"Failed to connect to {url}")
        except httpx.HTTPError as exc:
            logger.exception(f"Webhook {url} for {checkout_id} resulted in error: {exc}")
        except Exception as exc:
            logger.exception(f"Failed to call webhook at {url} for {checkout_id}: {exc}")
    except Checkout.DoesNotExist:
        logger.info(f"Checkout {checkout_id} does not exist")


@shared_task
def clear_expired_sessions():
    Session.objects.filter(expire_date__lte=timezone.now()).delete()
