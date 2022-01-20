import binascii
import logging

from django.core.management.base import BaseCommand
from web3.exceptions import TransactionNotFound

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import Chain, Transaction, TransactionDataRecord

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Records transaction data into database"

    def add_arguments(self, parser):
        parser.add_argument("transactions", metavar="N", nargs="+", type=str)
        parser.add_argument("--chain", dest="chain_id", required=True, type=int)

    def handle(self, *args, **options):

        chain_id = options["chain_id"]
        chain = Chain.active.get(id=chain_id)
        w3 = make_web3(provider=chain.provider)

        txs = options["transactions"]
        already_recorded = Transaction.objects.filter(
            block__chain_id=chain_id, hash__in=txs
        ).values_list("hash", flat=True)

        if already_recorded:
            logger.info(f"Transactions {', '.join(already_recorded)} already recorded")

        to_record = set(txs) - set(already_recorded)

        for tx_hash in to_record:
            try:
                tx_data = w3.eth.get_transaction(tx_hash)
                tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
                block_data = w3.eth.get_block(tx_data.blockHash)
                TransactionDataRecord.make(chain_id=chain_id, tx_data=tx_data)
                Transaction.make(
                    chain_id=chain_id,
                    block_data=block_data,
                    tx_receipt=tx_receipt,
                )
            except binascii.Error:
                logger.info(f"{tx_hash} is not a valid transaction hash")
            except TransactionNotFound:
                logger.info(f"{tx_hash} not found")
