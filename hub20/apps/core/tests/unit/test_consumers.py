import logging

import celery_pubsub
import pytest
from asgiref.sync import sync_to_async
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.sessions.models import Session
from django.core.asgi import get_asgi_application
from eth_utils import is_0x_prefixed

from hub20.apps.blockchain.factories import TransactionFactory
from hub20.apps.blockchain.models import BaseEthereumAccount
from hub20.apps.blockchain.tests.mocks import BlockMock
from hub20.apps.core.api import consumer_patterns
from hub20.apps.core.consumers import Events
from hub20.apps.core.factories import CheckoutFactory, Erc20TokenPaymentOrderFactory
from hub20.apps.core.middleware import TokenAuthMiddlewareStack
from hub20.apps.ethereum_money.models import EthereumToken
from hub20.apps.ethereum_money.signals import incoming_transfer_broadcast
from hub20.apps.ethereum_money.tests.mocks import Erc20TransferDataMock, Erc20TransferReceiptMock

logger = logging.getLogger(__name__)
application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": TokenAuthMiddlewareStack(URLRouter(consumer_patterns)),
    }
)


def make_payment_request():
    session = Session.objects.first()
    return Erc20TokenPaymentOrderFactory(session_key=session.session_key)


@pytest.fixture
def checkout():
    checkout = CheckoutFactory()
    checkout.store.accepted_currencies.add(checkout.currency)
    return checkout


@pytest.fixture
def blockchain_account(checkout):
    return BaseEthereumAccount.objects.filter(blockchain_routes__deposit=checkout).first()


@pytest.fixture
def transaction_params(checkout):
    route = checkout.routes.select_subclasses().first()
    return dict(
        blockNumber=checkout.currency.chain.highest_block,
        recipient=route.account.address,
        amount=checkout.as_token_amount,
    )


@pytest.fixture
def tx_data(checkout, transaction_params):
    return Erc20TransferDataMock(**transaction_params)


@pytest.fixture
def tx_receipt(checkout, tx_data, transaction_params):
    return Erc20TransferReceiptMock(
        hash=tx_data.hash,
        blockHash=tx_data.blockHash,
        from_address=tx_data["from"],
        transactionIndex=tx_data.transactionIndex,
        **transaction_params,
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_session_consumer():
    communicator = WebsocketCommunicator(application, "events")

    ok, protocol_or_error = await communicator.connect()
    assert ok, "Failed to connect"

    payment_request = await sync_to_async(make_payment_request)()

    account = await sync_to_async(
        payment_request.routes.values_list("blockchainpaymentroute__account", flat=True).first
    )()

    assert account is not None, "No account found"

    tx = await sync_to_async(TransactionFactory)()
    await sync_to_async(incoming_transfer_broadcast.send)(
        sender=EthereumToken,
        amount=payment_request.as_token_amount,
        account=account,
        transaction_hash=tx.hash_hex,
    )

    messages = []
    while not await communicator.receive_nothing(timeout=0.25):
        messages.append(await communicator.receive_json_from())

    await communicator.disconnect()

    assert len(messages) != 0, "we should have received something here"
    payment_sent_event = Events.BLOCKCHAIN_DEPOSIT_BROADCAST.value

    payment_sent_messages = [msg for msg in messages if msg["event"] == payment_sent_event]
    assert len(payment_sent_messages) == 1, "we should have received one payment received message"

    payment_sent_message = payment_sent_messages[0]
    assert "data" in payment_sent_message

    payment_data = payment_sent_message["data"]
    assert is_0x_prefixed(payment_data["transaction"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_checkout_consumer(checkout, blockchain_account, tx_data, tx_receipt):
    communicator = WebsocketCommunicator(application, f"checkout/{checkout.id}")

    ok, protocol_or_error = await communicator.connect()
    assert ok, "Failed to connect"

    assert blockchain_account is not None, "No account found"

    block_data = BlockMock(
        hash=tx_data.blockHash, number=tx_data.blockNumber, transactions=[tx_data.hash]
    )

    await sync_to_async(celery_pubsub.publish)(
        "blockchain.mined.transaction",
        chain_id=checkout.currency.chain_id,
        block_data=block_data,
        transaction_data=tx_data,
        transaction_receipt=tx_receipt,
    )

    messages = []
    while not await communicator.receive_nothing(timeout=0.25):
        messages.append(await communicator.receive_json_from())

    await communicator.disconnect()

    assert len(messages) != 0, "we should have received something here"
    payment_mined_event = Events.BLOCKCHAIN_DEPOSIT_RECEIVED.value

    payment_messages = [msg for msg in messages if msg["event"] == payment_mined_event]
    assert len(payment_messages) == 1, "we should have received one payment received message"

    payment_data = payment_messages[0]
    assert is_0x_prefixed(payment_data["transaction"])
    assert is_0x_prefixed(payment_data["token"])
    assert payment_data["amount"] == str(checkout.amount), "payment amount does not match"


__all__ = ["test_session_consumer"]
