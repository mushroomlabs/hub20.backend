import logging

import celery_pubsub
from celery import shared_task

logger = logging.getLogger(__name__)

from hub20.apps.blockchain.models import BaseEthereumAccount, Block, Chain, Transaction
from hub20.apps.blockchain.typing import Address

from . import signals
from .models import EthereumToken
from .abi import TRANSFER_EVENT_ABI, MINT_EVENT_ABI
from .client import get_transaction_events


def _get_or_create_transaction(chain_id, block_data, transaction_data, transaction_receipt):
    try:
        return Transaction.objects.get(hash=transaction_data.hash)
    except Transaction.DoesNotExist:
        block = Block.make(block_data, chain_id=chain_id)
        return Transaction.make(
            tx_data=transaction_data, tx_receipt=transaction_receipt, block=block
        )


@shared_task
def record_token_transactions(chain_id, block_data, transaction_data, transaction_receipt):
    recipient = transaction_data["to"]

    if EthereumToken.ERC20tokens.filter(chain_id=chain_id).filter(address=recipient).exists():
        logger.debug(f"Tx related to token {recipient} on chain {chain_id}")
        _get_or_create_transaction(chain_id, block_data, transaction_data, transaction_receipt)


@shared_task
def record_token_transfers(chain_id, block_data, transaction_data, transaction_receipt):
    events = get_transaction_events(transaction_receipt, TRANSFER_EVENT_ABI)
    if events:
        tx = _get_or_create_transaction(
            chain_id, block_data, transaction_data, transaction_receipt
        )

    for event in events:
        token_address = event.address
        token = EthereumToken.objects.filter(chain_id=chain_id, address=token_address).first()

        if not token:
            continue

        sender = event.args._from
        recipient = event.args._to

        amount = token.from_wei(event.args._value)

        for account in BaseEthereumAccount.objects.filter(address=sender):
            account.transactions.add(tx)
            signals.outgoing_transfer_mined.send(
                sender=Transaction,
                chain_id=chain_id,
                account=account,
                transaction=tx,
                amount=amount,
                address=recipient,
            )

        for account in BaseEthereumAccount.objects.filter(address=recipient):
            account.transactions.add(tx)
            signals.incoming_transfer_mined.send(
                sender=Transaction,
                chain_id=chain_id,
                account=account,
                transaction=tx,
                amount=amount,
                address=sender,
            )


@shared_task
def record_token_mints(chain_id, block_data, transaction_data, transaction_receipt):
    events = get_transaction_events(transaction_receipt, MINT_EVENT_ABI)

    for event in events:
        token_address = event.address
        recipient_address = event.args._to
        token = EthereumToken.objects.filter(chain_id=chain_id, address=token_address).first()

        if not token:
            continue

        account = BaseEthereumAccount.objects.filter(address=recipient_address).first()

        if not account:
            continue

        amount = token.from_wei(event.args._num)
        tx = _get_or_create_transaction(
            chain_id, block_data, transaction_data, transaction_receipt
        )

        account.transactions.add(tx)
        signals.incoming_transfer_mined.send(
            sender=Transaction,
            chain_id=chain_id,
            account=account,
            transaction=tx,
            amount=amount,
            address=token.address,
        )


@shared_task
def check_pending_transaction_for_eth_transfer(
    chain_id, transaction_data, account_address: Address
):
    sender = transaction_data["from"]
    recipient = transaction_data["to"]
    tx_hash = transaction_data["hash"]

    is_ETH_transfer = transaction_data.value != 0

    if is_ETH_transfer:
        chain = Chain.make(chain_id=chain_id)
        ETH = EthereumToken.ETH(chain=chain)
        account = BaseEthereumAccount.objects.get(address=account_address)
        amount = ETH.from_wei(transaction_data.value)

    if is_ETH_transfer and sender == account_address:
        signals.outgoing_transfer_broadcast.send(
            sender=Transaction,
            chain_id=chain_id,
            account=account,
            amount=amount,
            transaction_hash=tx_hash,
        )

    if is_ETH_transfer and recipient == account_address:
        signals.incoming_transfer_broadcast.send(
            sender=Transaction,
            chain_id=chain_id,
            account=account,
            amount=amount,
            transaction_hash=tx_hash,
        )


@shared_task
def check_mined_transaction_for_eth_transfer(
    chain_id, block_data, transaction_data, transaction_receipt, account_address: Address
):
    sender = transaction_data["from"]
    recipient = transaction_data["to"]
    tx_hash = transaction_data["hash"]

    is_ETH_transfer = transaction_data.value != 0

    if is_ETH_transfer:
        chain = Chain.make(chain_id=chain_id)
        ETH = EthereumToken.ETH(chain=chain)
        account = BaseEthereumAccount.objects.get(address=account_address)
        amount = ETH.from_wei(transaction_data.value)

    if account_address in [sender, recipient]:
        try:
            tx = Transaction.objects.get(chain_id=chain_id, hash=tx_hash)
        except Transaction.DoesNotExist:
            logger.warning("Transaction {tx_hash.hex()} is not recorded on the database")
            block = Block.make(block_data, chain_id=chain_id)
            tx = Transaction.make(
                tx_data=transaction_data, tx_receipt=transaction_receipt, block=block
            )

    if is_ETH_transfer and sender == account_address:
        account.transactions.add(tx)
        signals.outgoing_transfer_mined.send(
            sender=Transaction,
            chain_id=chain_id,
            account=account,
            amount=amount,
            transaction=tx,
            address=recipient,
        )

    if is_ETH_transfer and recipient == account_address:
        account.transactions.add(tx)
        signals.incoming_transfer_mined.send(
            sender=Transaction,
            chain_id=chain_id,
            account=account,
            amount=amount,
            transaction=tx,
            address=sender,
        )


celery_pubsub.subscribe("blockchain.transaction.mined", record_token_transactions)
celery_pubsub.subscribe("blockchain.transaction.mined", record_token_transfers)
celery_pubsub.subscribe("blockchain.transaction.mined", record_token_mints)
celery_pubsub.subscribe("account.transaction.pending", check_pending_transaction_for_eth_transfer)
celery_pubsub.subscribe("account.transaction.mined", check_mined_transaction_for_eth_transfer)
