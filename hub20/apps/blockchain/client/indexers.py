import logging
from typing import Optional

from django.db import IntegrityError, transaction
from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import TimeExhausted, TransactionNotFound

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.models import Block, Chain, Transaction

from .utils import wait_for_connection

logger = logging.getLogger(__name__)


def get_block_by_hash(w3: Web3, block_hash: HexBytes) -> Optional[Block]:
    try:
        chain = Chain.objects.get(id=int(w3.net.version))
        block_data = w3.eth.get_block(block_hash)
        return Block.make(block_data, chain.id)
    except (AttributeError, Chain.DoesNotExist):
        return None


def get_transaction_by_hash(
    w3: Web3, transaction_hash: HexBytes, block: Optional[Block] = None
) -> Optional[Transaction]:
    try:
        tx_data = w3.eth.getTransaction(transaction_hash)

        if block is None:
            block = get_block_by_hash(w3=w3, block_hash=tx_data.blockHash)

        assert block is not None

        try:
            with transaction.atomic():
                return Transaction.make(
                    tx_data=tx_data,
                    tx_receipt=w3.eth.getTransactionReceipt(transaction_hash),
                    block=block,
                )
        except IntegrityError:
            chain_id = int(w3.net.version)
            return Transaction.objects.filter(hash=transaction_hash, chain_id=chain_id).first()

    except (TransactionNotFound, AssertionError):
        return None


def get_block_by_number(w3: Web3, block_number: int) -> Optional[Block]:
    chain_id = int(w3.net.version)
    try:
        block_data = w3.eth.get_block(block_number, full_transactions=True)
    except AttributeError:
        return None

    logger.info(f"Making block #{block_number} with {len(block_data.transactions)} transactions")
    with transaction.atomic():
        block = Block.make(block_data, chain_id=chain_id)
        for tx_data in block_data.transactions:
            try:
                tx_hash = tx_data.hash.hex()
                Transaction.make(
                    tx_data=tx_data,
                    tx_receipt=w3.eth.waitForTransactionReceipt(tx_hash),
                    block=block,
                )
            except TimeExhausted:
                logger.warning(f"Timeout when trying to get transaction {tx_hash}")
        return block


def run_backfill(w3: Web3, start: int, end: int):
    chain_id = int(w3.net.version)
    block_range = (start, end)
    chain_blocks = Block.objects.filter(chain_id=chain_id, number__range=block_range)
    recorded_block_set = set(chain_blocks.values_list("number", flat=True))
    range_set = set(range(*block_range))
    missing_blocks = list(range_set.difference(recorded_block_set))[::]

    for block_number in missing_blocks:
        get_block_by_number(w3=w3, block_number=block_number)


def download_all_chain(w3: Web3, **kw):
    wait_for_connection(w3)
    start = 0
    highest = w3.eth.blockNumber
    while start < highest:
        wait_for_connection(w3)
        end = min(start + BLOCK_SCAN_RANGE, highest)
        logger.info(f"Syncing blocks between {start} and {end}")
        run_backfill(w3=w3, start=start, end=end)
        start = end
