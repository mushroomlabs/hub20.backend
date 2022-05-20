import logging
from asyncio.exceptions import TimeoutError

import celery_pubsub
from celery import shared_task
from django.db.models import Q
from web3 import Web3
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params
from web3.exceptions import LogTopicError, TransactionNotFound

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import (
    BaseEthereumAccount,
    Chain,
    EventIndexer,
    Transaction,
    TransactionDataRecord,
    Web3Provider,
)
from hub20.apps.blockchain.tasks import stream_processor_lock
from hub20.apps.ethereum_money.abi import EIP20_ABI

from . import signals
from .models import Token, TokenList, TransferEvent

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def index_token_transfer_events(self):
    indexer_name = "ethereum_money:token_transfers"

    account_addresses = BaseEthereumAccount.objects.values_list("address", flat=True)

    for provider in Web3Provider.available.select_related("chain"):
        event_indexer = EventIndexer.make(provider.chain_id, indexer_name)
        w3: Web3 = make_web3(provider=provider)

        current_block = w3.eth.block_number

        contract = w3.eth.contract(abi=EIP20_ABI)
        abi = contract.events.Transfer._get_event_abi()

        with stream_processor_lock(task=self, provider=provider) as lock:
            while event_indexer.last_block < current_block and lock.is_acquired:
                last_processed = event_indexer.last_block

                from_block = last_processed
                to_block = min(current_block, from_block + provider.max_block_scan_range)

                logger.debug(f"Getting {indexer_name} events between {from_block} and {to_block}")

                _, event_filter_params = construct_event_filter_params(
                    abi, w3.codec, fromBlock=from_block, toBlock=to_block
                )
                try:
                    for log in w3.eth.get_logs(event_filter_params):
                        try:
                            event_data = get_event_data(w3.codec, abi, log)
                            sender = event_data.args._from
                            recipient = event_data.args._to

                            if sender in account_addresses:
                                celery_pubsub.publish(
                                    "blockchain.event.token_transfer.mined",
                                    chain_id=w3.eth.chain_id,
                                    wallet_address=sender,
                                    event_data=event_data,
                                    provider_url=provider.url,
                                )

                            if recipient in account_addresses:
                                celery_pubsub.publish(
                                    "blockchain.event.token_transfer.mined",
                                    chain_id=w3.eth.chain_id,
                                    wallet_address=recipient,
                                    event_data=event_data,
                                    provider_url=provider.url,
                                )

                        except LogTopicError:
                            pass
                        except Exception as exc:
                            logger.exception(f"Unknown error when processing transfer log: {exc}")
                except TimeoutError:
                    logger.error(f"Timeout when getting logs from {provider.hostname}")
                    continue
                except Exception as exc:
                    logger.error(f"Error getting logs from {provider.hostname}: {exc}")
                    continue

                event_indexer.last_block = to_block
                event_indexer.save()

                lock.refresh()


@shared_task
def import_token_list(url, description=None):
    token_list_data = TokenList.fetch(url)
    TokenList.make(url, token_list_data, description=description)


@shared_task
def record_token_transfers(chain_id, wallet_address, event_data, provider_url):
    token_address = event_data.address
    token = Token.objects.filter(chain_id=chain_id, address=token_address).first()

    if not token:
        return

    sender = event_data.args._from
    recipient = event_data.args._to

    try:
        provider = Web3Provider.objects.get(url=provider_url)
        w3 = make_web3(provider=provider)

        tx_data = w3.eth.get_transaction(event_data.transactionHash)
        tx_receipt = w3.eth.get_transaction_receipt(event_data.transactionHash)
        block_data = w3.eth.get_block(tx_receipt.blockHash)
        amount = token.from_wei(event_data.args._value)

        TransactionDataRecord.make(chain_id=chain_id, tx_data=tx_data)
        tx = Transaction.make(chain_id=chain_id, block_data=block_data, tx_receipt=tx_receipt)

        TransferEvent.objects.create(
            transaction=tx,
            sender=sender,
            recipient=recipient,
            amount=amount.amount,
            currency=amount.currency,
            log_index=event_data.logIndex,
        )

    except TransactionNotFound:
        logger.warning(f"Failed to get transaction {event_data.transactionHash.hex()}")
        return

    tx_hash = event_data.transactionHash.hex()

    account = BaseEthereumAccount.objects.filter(address=wallet_address).first()

    if not account:
        logger.warn(f"{wallet_address} is not associated with any known account")
        return

    if account.address == sender:
        logger.debug(
            f"Sending signal of outgoing transfer mined from {account.address} on tx {tx_hash}"
        )
        account.transactions.add(tx)
        signals.outgoing_transfer_mined.send(
            sender=Transaction,
            account=account,
            transaction=tx,
            amount=amount,
            address=recipient,
        )
    elif account.address == recipient:
        logger.debug(
            f"Sending signal of incoming transfer mined from {account.address} on tx {tx_hash}"
        )
        account.transactions.add(tx)
        signals.incoming_transfer_mined.send(
            sender=Transaction,
            account=account,
            transaction=tx,
            amount=amount,
            address=sender,
        )
    else:
        logger.warn(f"Transfer on {tx_hash} generated but is not related to {wallet_address}")


@shared_task
def check_eth_transfers(chain_id, block_data, provider_url):
    addresses = BaseEthereumAccount.objects.values_list("address", flat=True)

    txs = [
        t
        for t in block_data["transactions"]
        if t.value > 0 and (t["to"] in addresses or t["from"] in addresses)
    ]

    if not txs:
        return

    chain = Chain.active.get(id=chain_id)
    provider = Web3Provider.objects.get(url=provider_url)
    w3 = make_web3(provider=provider)

    assert chain == provider.chain, f"{provider.hostname} not connected to {chain.name}"

    native_token = Token.make_native(chain=chain)

    for transaction_data in txs:
        sender = transaction_data["from"]
        recipient = transaction_data["to"]

        amount = native_token.from_wei(transaction_data.value)

        transaction_receipt = w3.eth.get_transaction_receipt(transaction_data.hash)
        tx = Transaction.make(
            chain_id=chain_id,
            block_data=block_data,
            tx_receipt=transaction_receipt,
        )

        TransferEvent.objects.create(
            transaction=tx,
            sender=sender,
            recipient=recipient,
            amount=amount.amount,
            currency=amount.currency,
        )
        for account in BaseEthereumAccount.objects.filter(address=sender):
            account.transactions.add(tx)
            signals.outgoing_transfer_mined.send(
                sender=Transaction,
                account=account,
                amount=amount,
                transaction=tx,
                address=recipient,
            )

        for account in BaseEthereumAccount.objects.filter(address=recipient):
            account.transactions.add(tx)
            signals.incoming_transfer_mined.send(
                sender=Transaction,
                account=account,
                amount=amount,
                transaction=tx,
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

    native_token = Token.make_native(chain=chain)
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
            sender=Token,
            account=account,
            amount=amount,
            transaction_data=tx_data,
        )


@shared_task
def check_pending_erc20_transfer_event(chain_id, event_data, provider_url):
    try:
        token = Token.objects.get(chain_id=chain_id, address=event_data.address)
    except Token.DoesNotExist:
        return

    sender = event_data.args._from
    recipient = event_data.args._to

    if not BaseEthereumAccount.objects.filter(Q(address=sender) | Q(address=recipient)).exists():
        return

    amount = token.from_wei(event_data.args._value)

    try:
        provider = Web3Provider.objects.get(url=provider_url)
        w3 = make_web3(provider=provider)
        transaction_data = w3.eth.get_transaction(event_data.transactionHash)
    except TransactionNotFound:
        logger.warning(f"Failed to get transaction data {event_data.transactionHash.hex()}")
        return

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


celery_pubsub.subscribe("blockchain.event.token_transfer.mined", record_token_transfers)
celery_pubsub.subscribe("blockchain.mined.block", check_eth_transfers)
celery_pubsub.subscribe(
    "blockchain.broadcast.transaction", check_pending_transaction_for_eth_transfer
)
celery_pubsub.subscribe(
    "blockchain.event.token_transfer.broadcast", check_pending_erc20_transfer_event
)
