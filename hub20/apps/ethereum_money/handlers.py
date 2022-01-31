import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from hub20.apps.blockchain.models import Chain

from .models import EthereumToken

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Chain)
def on_chain_created_create_native_token(sender, **kw):
    if kw["created"]:
        chain = kw["instance"]
        EthereumToken.make_native(chain)
