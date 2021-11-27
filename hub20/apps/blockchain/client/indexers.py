import logging
from typing import Optional

from django.db import IntegrityError, transaction
from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain.models import Block, Chain, Transaction


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
