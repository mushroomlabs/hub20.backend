import logging

import celery_pubsub
from celery import shared_task
from django.db.transaction import atomic

from .models import BaseEthereumAccount, Block, Chain, Transaction
from .signals import block_sealed

logger = logging.getLogger(__name__)


@shared_task
def check_blockchain_height(chain_id, block_data):
    chain = Chain.active.get(id=chain_id)

    with atomic():
        block_number = block_data["number"]
        if chain.highest_block > block_number:
            chain.blocks.filter(number__gt=block_number).delete()

        chain.highest_block = block_number
        chain.save()

    block_sealed.send(sender=Block, chain_id=chain_id, block_data=block_data)


@shared_task
def record_account_transactions(chain_id, block_data, transaction_data, transaction_receipt):
    sender = transaction_data["from"]
    recipient = transaction_data["to"]

    logger.debug(f"Tx mined from {sender} to {recipient} on chain {chain_id}")

    for account in BaseEthereumAccount.objects.filter(address__in=[sender, recipient]):
        Transaction.make(
            chain_id=chain_id,
            tx_data=transaction_data,
            tx_receipt=transaction_receipt,
            block_data=block_data,
        )


@shared_task
def set_node_connection_ok(chain_id, provider_url):
    logger.debug(f"Setting node {provider_url} to online")
    Chain.objects.filter(id=chain_id, provider_url=provider_url).update(online=True)


@shared_task
def set_node_connection_nok(chain_id, provider_url):
    Chain.objects.filter(id=chain_id, provider_url=provider_url).update(online=False)


@shared_task
def set_node_sync_ok(chain_id, provider_url):
    Chain.objects.filter(id=chain_id, provider_url=provider_url).update(synced=True)


@shared_task
def set_node_sync_nok(chain_id, provider_url):
    Chain.objects.filter(id=chain_id, provider_url=provider_url).update(synced=False)


celery_pubsub.subscribe("blockchain.mined.block", check_blockchain_height)
celery_pubsub.subscribe("blockchain.mined.transaction", record_account_transactions)
celery_pubsub.subscribe("node.connection.ok", set_node_connection_ok)
celery_pubsub.subscribe("node.connection.nok", set_node_connection_nok)
celery_pubsub.subscribe("node.sync.ok", set_node_sync_ok)
celery_pubsub.subscribe("node.sync.nok", set_node_sync_nok)
