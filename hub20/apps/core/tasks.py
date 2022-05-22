import logging
from contextlib import contextmanager
from hashlib import md5

import httpx
from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

from .consumers import CheckoutConsumer, Events, SessionEventsConsumer
from .models import Checkout, TokenList, Transfer

User = get_user_model()
logger = logging.getLogger(__name__)


def _get_open_session_keys():
    now = timezone.now()
    return Session.objects.filter(expire_date__gt=now).values_list("session_key", flat=True)


STREAM_PROCESSOR_LOCK_INTERVAL = 20  # in seconds


class ProviderTaskLock:
    def __init__(self, task, provider, timeout=STREAM_PROCESSOR_LOCK_INTERVAL):
        self.task = task
        self.provider = provider
        self.timeout = timeout
        self.is_acquired = False

        hsh = md5(f"{self.provider.hostname}-{self.task.name}".encode())
        self.key = hsh.hexdigest()

    def acquire(self):
        # cache.add fails if the key already exists
        self.is_acquired = cache.add(self.key, self.task.request.id, self.timeout)

    def refresh(self):
        logger.debug(f"Refreshing lock for {self.provider.hostname} on {self.task.name}")
        self.is_acquired = self.is_acquired and cache.touch(self.key, self.timeout)

    def release(self):
        if self.is_acquired:
            logger.debug(f"Releasing lock for {self.provider.hostname} on {self.task.name}")
            cache.delete(self.key)


@contextmanager
def stream_processor_lock(task, provider, timeout=STREAM_PROCESSOR_LOCK_INTERVAL):
    """
    The context manager should be called from any non-idempotent
    task that process incoming data from a provider. It creates a lock for
    the exclusive task/provider pair which expires with `timeout` seconds.
    If the task may run for a indetermined period, it can make calls
    to lock.refresh in order to reset the lock timer.
    """

    logger.debug(f"Attempting lock for {provider.hostname} on task {task.name}")
    lock = ProviderTaskLock(task=task, provider=provider, timeout=timeout)

    lock.acquire()

    try:
        yield lock
    finally:
        lock.release()


@shared_task
def broadcast_event(**kw):
    for session_key in _get_open_session_keys():
        send_session_event(session_key, **kw)


@shared_task
def execute_transfer(transfer_id):
    try:
        transfer = Transfer.pending.get(id=transfer_id)
        transfer.execute()
    except Transfer.DoesNotExist:
        logger.warning(f"Transfer {transfer_id} not found or already confirmed")


@shared_task
def execute_pending_transfers():
    for transfer in Transfer.pending.exclude(execute_on__gt=timezone.now()):
        transfer.execute()


@shared_task
def send_session_event(session_key, event, **event_data):
    layer = get_channel_layer()
    channel_group_name = SessionEventsConsumer.get_group_name(session_key)
    event_data.update({"type": "notify_event", "event": event})
    logger.info(f"Sending {event} to session {session_key}")
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
            logger.warning(f"Webhook {url} for {checkout_id} resulted in error response: {exc}")
        except Exception as exc:
            logger.exception(f"Failed to call webhook at {url} for {checkout_id}: {exc}")
    except Checkout.DoesNotExist:
        logger.info(f"Checkout {checkout_id} does not exist")


@shared_task
def import_token_list(url, description=None):
    token_list_data = TokenList.fetch(url)
    TokenList.make(url, token_list_data, description=description)


@shared_task
def notify_block_created(chain_id, block_data):
    logger.debug(f"Sending notification of of block created on #{chain_id}")
    block_number = block_data["number"]
    session_keys = _get_open_session_keys()
    logger.info(f"Notifying {len(session_keys)} clients about block #{block_number}")
    for session_key in session_keys:
        event_data = dict(
            chain_id=chain_id,
            hash=block_data.hash.hex(),
            number=block_number,
            timestamp=block_data.timestamp,
        )
        send_session_event(session_key, event=Events.BLOCKCHAIN_BLOCK_CREATED.value, **event_data)


@shared_task
def clear_expired_sessions():
    Session.objects.filter(expire_date__lte=timezone.now()).delete()
