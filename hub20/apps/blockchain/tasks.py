import logging

import celery_pubsub
from celery import shared_task
from django.db.transaction import atomic

logger = logging.getLogger(__name__)

from .models import BaseEthereumAccount, Block, Chain, Transaction


@shared_task
@atomic()
def check_blockchain_height(chain_id, block_data):
    chain = Chain.make(chain_id=chain_id)

    block_number = block_data["number"]

    if chain.highest_block > block_data["number"]:
        chain.blocks.filter(number__gt=block_number).delete()

    chain.highest_block = block_number
    chain.save()


@shared_task
def record_account_transactions(chain_id, block_data, transaction_data, transaction_receipt):
    sender = transaction_data["from"]
    recipient = transaction_data["to"]

    logger.debug(f"Tx mined from {sender} to {recipient} on chain {chain_id}")

    for account in BaseEthereumAccount.objects.filter(address__in=[sender, recipient]):
        block = Block.make(block_data, chain_id=chain_id)
        Transaction.make(tx_data=transaction_data, tx_receipt=transaction_receipt, block=block)


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


celery_pubsub.subscribe("blockchain.block.mined", check_blockchain_height)
celery_pubsub.subscribe("blockchain.transaction.mined", record_account_transactions)
celery_pubsub.subscribe("node.connection.ok", set_node_connection_ok)
celery_pubsub.subscribe("node.connection.nok", set_node_connection_nok)
celery_pubsub.subscribe("node.sync.ok", set_node_sync_ok)
celery_pubsub.subscribe("node.sync.nok", set_node_sync_nok)
