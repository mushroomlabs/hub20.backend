import logging

import celery_pubsub
from celery import shared_task

logger = logging.getLogger(__name__)

from hub20.apps.blockchain.models import (
    BaseEthereumAccount,
    Chain,
    Transaction,
    TransactionDataRecord,
)

from . import signals
from .abi import TRANSFER_EVENT_ABI
from .client import get_transaction_events
from .models import EthereumToken


@shared_task
def record_token_transactions(chain_id, block_data, transaction_data, transaction_receipt):
    recipient = transaction_data["to"]

    if EthereumToken.ERC20tokens.filter(chain_id=chain_id).filter(address=recipient).exists():
        logger.debug(f"Tx related to token {recipient} on chain {chain_id}")
        Transaction.make(
            chain_id=chain_id,
            block_data=block_data,
            tx_receipt=transaction_receipt,
        )


@shared_task
def record_token_transfers(chain_id, block_data, transaction_data, transaction_receipt):
    events = get_transaction_events(transaction_receipt, TRANSFER_EVENT_ABI)
    if events:
        tx = Transaction.make(
            chain_id=chain_id,
            block_data=block_data,
            tx_receipt=transaction_receipt,
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
                account=account,
                transaction=tx,
                amount=amount,
                address=recipient,
            )

        for account in BaseEthereumAccount.objects.filter(address=recipient):
            account.transactions.add(tx)
            signals.incoming_transfer_mined.send(
                sender=Transaction,
                account=account,
                transaction=tx,
                amount=amount,
                address=sender,
            )


@shared_task
def check_pending_transaction_for_eth_transfer(chain_id, transaction_data):
    chain = Chain.actve.get(id=chain_id)

    sender = transaction_data["from"]
    recipient = transaction_data["to"]

    is_native_token_transfer = transaction_data.value != 0

    if not is_native_token_transfer:
        return

    native_token = EthereumToken.make_native(chain=chain)
    amount = native_token.from_wei(transaction_data.value)

    for account in BaseEthereumAccount.objects.filter(address=sender):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)

        signals.outgoing_transfer_broadcast.send(
            sender=TransactionDataRecord,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )

    for account in BaseEthereumAccount.objects.filter(address=recipient):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)

        signals.incoming_transfer_broadcast.send(
            sender=EthereumToken,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )


@shared_task
def check_pending_erc20_transfer_event(chain_id, transaction_data, event):
    try:
        token = EthereumToken.objects.get(chain_id=chain_id, address=event.address)
    except EthereumToken.DoesNotExist:
        return

    sender = event.args._from
    recipient = event.args._to
    amount = token.from_wei(event.args._value)

    for account in BaseEthereumAccount.objects.filter(address=sender):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)
        signals.outgoing_transfer_broadcast.send(
            sender=TransactionDataRecord,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )

    for account in BaseEthereumAccount.objects.filter(address=recipient):
        tx_data = TransactionDataRecord.make(tx_data=transaction_data, chain_id=chain_id)
        signals.incoming_transfer_broadcast.send(
            sender=TransactionDataRecord,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )


@shared_task
def check_mined_transaction_for_eth_transfer(
    chain_id, block_data, transaction_data, transaction_receipt
):
    chain = Chain.active.get(id=chain_id)
    sender = transaction_data["from"]
    recipient = transaction_data["to"]

    is_native_token_transfer = transaction_data.value != 0

    if not is_native_token_transfer:
        return

    if not BaseEthereumAccount.objects.filter(address__in=[sender, recipient]).exists():
        return

    native_token = EthereumToken.make_native(chain=chain)
    amount = native_token.from_wei(transaction_data.value)
    tx = Transaction.make(
        chain_id=chain_id,
        block_data=block_data,
        tx_receipt=transaction_receipt,
    )

    for account in BaseEthereumAccount.objects.filter(address=sender):
        account.transactions.add(tx)
        signals.outgoing_transfer_mined.send(
            sender=Transaction,
            chain_id=chain_id,
            account=account,
            amount=amount,
            transaction=tx,
            address=recipient,
        )

    for account in BaseEthereumAccount.objects.filter(address=recipient):
        account.transactions.add(tx)
        signals.incoming_transfer_mined.send(
            sender=Transaction,
            chain_id=chain_id,
            account=account,
            amount=amount,
            transaction=tx,
            address=sender,
        )


celery_pubsub.subscribe("blockchain.mined.transaction", record_token_transactions)
celery_pubsub.subscribe("blockchain.mined.transaction", record_token_transfers)
celery_pubsub.subscribe("blockchain.mined.transaction", check_mined_transaction_for_eth_transfer)
celery_pubsub.subscribe(
    "blockchain.broadcast.transaction", check_pending_transaction_for_eth_transfer
)
celery_pubsub.subscribe("blockchain.broadcast.event", check_pending_erc20_transfer_event)
