import asyncio
import logging

from asgiref.sync import sync_to_async
from web3 import Web3
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain import signals
from hub20.apps.blockchain.models import Block, Chain, Transaction

from .constants import BLOCK_CREATION_INTERVAL
from .decorators import web3_filter_event_handler
from .web3 import make_web3

logger = logging.getLogger(__name__)


async def node_status_changes():
    while True:
        chains = await sync_to_async(list)(Chain.objects.all())
        for chain in chains:
            w3 = make_web3(provider_url=chain.provider_url)
            try:
                has_peers = w3.net.peer_count > 0
                is_synced = bool(not w3.eth.syncing)
            except ValueError:
                # The node does not support the method. Assume it has peers
                is_synced = True
                has_peers = True
            await sync_to_async(signals.chain_status_synced.send)(
                sender=Chain,
                chain_id=w3.eth.chain_id,
                current_block=w3.eth.blockNumber,
                synced=is_synced and has_peers,
            )
        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


@web3_filter_event_handler(filter_type="latest", polling_interval=BLOCK_CREATION_INTERVAL / 2)
async def process_new_block(w3: Web3, chain: Chain, event):
    logger.info(f"New block: {event.hex()}")
    block_data = w3.eth.get_block(event, full_transactions=True)
    await sync_to_async(signals.block_sealed.send)(
        sender=Block, chain_id=w3.eth.chain_id, block_data=block_data
    )
    for tx_data in block_data["transactions"]:
        try:
            tx_receipt = w3.eth.get_transaction_receipt(tx_data.hash)
            await sync_to_async(signals.transaction_mined.send)(
                sender=Transaction,
                chain_id=w3.eth.chain_id,
                block_data=block_data,
                transaction_data=tx_data,
                transaction_receipt=tx_receipt,
            )
        except TransactionNotFound:
            pass


@web3_filter_event_handler(filter_type="pending", polling_interval=2)
async def process_pending_transaction(w3: Web3, chain: Chain, event):
    tx_hash = event.hex()
    logger.info(f"Pending tx broadcast: {tx_hash}")
    try:
        tx_data = w3.eth.getTransaction(tx_hash)
        logger.debug(f"{tx_data['to']} to {tx_data['from']}")
        await sync_to_async(signals.transaction_broadcast.send)(
            sender=Transaction, chain_id=w3.eth.chain_id, transaction_data=tx_data
        )
    except TransactionNotFound:
        logger.info(f"Transaction {tx_hash} not found at pending status")
