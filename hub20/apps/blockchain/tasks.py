import logging

from celery import shared_task

logger = logging.getLogger(__name__)

from .models import BaseEthereumAccount, Block, Transaction


@shared_task
def record_account_transactions(chain_id, block_data, transaction_data, transaction_receipt):
    sender = transaction_data["from"]
    recipient = transaction_data["to"]

    logger.debug(f"Tx mined from {sender} to {recipient} on chain {chain_id}")

    if BaseEthereumAccount.objects.filter(address__in=[sender, recipient]).exists():
        block = Block.make(block_data, chain_id=chain_id)
        Transaction.make(tx_data=transaction_data, tx_receipt=transaction_receipt, block=block)
