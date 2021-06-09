import logging
from typing import Dict

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.dispatch import receiver
from django.utils import timezone

from hub20.apps.blockchain.models import Block, Chain
from hub20.apps.blockchain.signals import (
    block_sealed,
    ethereum_node_connected,
    ethereum_node_disconnected,
    ethereum_node_sync_lost,
    ethereum_node_sync_recovered,
)
from hub20.apps.core import tasks
from hub20.apps.core.consumers import Events

User = get_user_model()
logger = logging.getLogger(__name__)


def _get_open_session_keys():
    now = timezone.now()
    return Session.objects.filter(expire_date__gt=now).values_list("session_key", flat=True)


@receiver(block_sealed, sender=Block)
def on_block_sealed_send_notification(sender, **kw):

    block_data: Dict = kw["block_data"]

    block_number = block_data["number"]
    session_keys = _get_open_session_keys()
    logger.info(f"Notifying {len(session_keys)} clients about block #{block_number}")
    for session_key in session_keys:
        tasks.send_session_event.delay(
            session_key,
            event=Events.BLOCKCHAIN_BLOCK_CREATED.value,
            **{
                k: v
                for k, v in block_data.items()
                if k in ["gasUsed", "hash", "nonce", "number", "parentsHash", "size", "timestamp"]
            },
        )


@receiver(ethereum_node_disconnected, sender=Chain)
@receiver(ethereum_node_sync_lost, sender=Chain)
def on_ethereum_node_error_send_notification(sender, **kw):
    chain_id = kw["chain_id"]
    for session_key in _get_open_session_keys():
        tasks.send_session_event.delay(
            session_key, event=Events.ETHEREUM_NODE_UNAVAILABLE.value, chain_id=chain_id
        )


@receiver(ethereum_node_connected, sender=Chain)
@receiver(ethereum_node_sync_recovered, sender=Chain)
def on_ethereum_node_ok_send_notification(sender, **kw):
    chain_id = kw["chain_id"]
    for session_key in _get_open_session_keys():
        tasks.send_session_event.delay(
            session_key, event=Events.ETHEREUM_NODE_OK.value, chain_id=chain_id
        )


__all__ = [
    "on_block_sealed_send_notification",
    "on_ethereum_node_error_send_notification",
    "on_ethereum_node_ok_send_notification",
]
