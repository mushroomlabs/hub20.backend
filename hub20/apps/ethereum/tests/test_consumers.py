from decimal import Decimal

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from eth_utils import is_0x_prefixed
from web3 import Web3

from hub20.apps.core.factories.networks import InternalPaymentNetworkFactory, SiteFactory
from hub20.apps.core.settings import app_settings
from hub20.apps.core.tests.asgi import application

from .. import handlers
from ..abi.tokens import EIP20_ABI
from ..constants import Events
from ..factories import (
    BlockFactory,
    Erc20TokenBlockchainPaymentFactory,
    Erc20TokenCheckoutFactory,
    Erc20TokenPaymentOrderFactory,
)
from ..models import BaseWallet, Block, Chain
from ..signals import block_sealed
from .mocks import BlockMock, Erc20TokenTransferDataMock, Erc20TokenTransferReceiptMock


def deposit_account(payment_request):
    return BaseWallet.objects.filter(blockchain_routes__deposit=payment_request).first()


def deposit_transaction_params(payment_request):
    route = payment_request.routes.select_subclasses().first()
    return dict(
        blockNumber=payment_request.currency.chain.highest_block,
        recipient=route.account.address,
        amount=payment_request.as_token_amount,
    )


def deposit_tx_data(deposit_tx_params):
    return Erc20TokenTransferDataMock(**deposit_tx_params)


def deposit_tx_receipt(tx_data, tx_params):
    return Erc20TokenTransferReceiptMock(
        hash=tx_data.hash,
        blockHash=tx_data.blockHash,
        from_address=tx_data["from"],
        transactionIndex=tx_data.transactionIndex,
        **tx_params,
    )


def deposit_block_data(tx_data):
    return BlockMock(
        hash=tx_data.blockHash,
        number=tx_data.blockNumber,
        transactions=[tx_data.hash],
    )


def erc20_deposit_transfer_events(tx_data, tx_params):
    w3 = Web3()
    tx_receipt = deposit_tx_receipt(tx_data, tx_params)
    contract = w3.eth.contract(address=tx_receipt.to, abi=EIP20_ABI)
    return contract.events.Transfer().processReceipt(tx_receipt)


@pytest.fixture
def session_events_communicator(client):
    communicator = WebsocketCommunicator(application, "events")
    communicator.scope["session"] = client.session

    return communicator


@pytest.fixture
def hub_site():
    return SiteFactory()


@pytest.fixture
def treasury(hub_site):
    return InternalPaymentNetworkFactory(site=hub_site)


@pytest.fixture
def checkout():
    checkout = Erc20TokenCheckoutFactory()
    checkout.store.accepted_token_list.tokens.add(checkout.order.currency)
    return checkout


@pytest.fixture
def erc20_payment_request(client):
    return Erc20TokenPaymentOrderFactory(session_key=client.session.session_key)


@pytest.fixture
def erc20_blockchain_payment(erc20_payment_request):
    return Erc20TokenBlockchainPaymentFactory(route__deposit=erc20_payment_request)


@pytest.fixture
def erc20_blockchain_checkout_payment(checkout):
    return Erc20TokenBlockchainPaymentFactory(
        currency=checkout.order.currency,
        amount=checkout.order.amount,
        route__deposit=checkout.order,
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_session_receives_token_deposit_received(
    session_events_communicator,
    erc20_blockchain_payment,
):

    ok, protocol_or_error = await session_events_communicator.connect()
    assert ok, "Failed to connect"

    await sync_to_async(handlers.on_blockchain_payment_received_send_notification)(
        sender=erc20_blockchain_payment.__class__, payment=erc20_blockchain_payment
    )

    messages = []
    while not await session_events_communicator.receive_nothing(timeout=0.25):
        messages.append(await session_events_communicator.receive_json_from())

    await session_events_communicator.disconnect()

    assert len(messages) != 0, "we should have received something here"
    payment_received_event = Events.DEPOSIT_RECEIVED.value

    payment_received_messages = [msg for msg in messages if msg["event"] == payment_received_event]
    assert len(payment_received_messages) == 1, "we should have a payment received message"

    payment_message = payment_received_messages[0]
    assert "data" in payment_message

    payment_data = payment_message["data"]
    assert is_0x_prefixed(payment_data["transaction"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_checkout_receives_block_created_notification(
    checkout, erc20_blockchain_checkout_payment
):
    communicator = WebsocketCommunicator(application, f"checkout/{checkout.id}")

    ok, protocol_or_error = await communicator.connect()
    assert ok, "Failed to connect"

    block_data = BlockMock()

    await sync_to_async(block_sealed.send)(
        sender=Block, chain_id=checkout.order.currency.chain_id, block_data=block_data
    )

    messages = []
    while not await communicator.receive_nothing(timeout=0.25):
        messages.append(await communicator.receive_json_from())

    await communicator.disconnect()

    assert len(messages) != 0, "we should have received something here"

    block_created_messages = [
        msg for msg in messages if msg["event"] == Events.BLOCK_CREATED.value
    ]
    assert len(block_created_messages) == 1, "we should have received one block created message"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_checkout_receives_transaction_mined_notification(
    checkout, erc20_blockchain_checkout_payment
):
    communicator = WebsocketCommunicator(application, f"checkout/{checkout.id}")

    ok, protocol_or_error = await communicator.connect()
    assert ok, "Failed to connect"

    payment = erc20_blockchain_checkout_payment

    await sync_to_async(handlers.on_blockchain_payment_received_send_notification)(
        sender=payment.__class__, payment=payment
    )

    messages = []
    while not await communicator.receive_nothing(timeout=0.25):
        messages.append(await communicator.receive_json_from())

    await communicator.disconnect()

    assert len(messages) != 0, "we should have received something here"
    payment_mined_event = Events.DEPOSIT_RECEIVED.value

    payment_messages = [msg for msg in messages if msg["event"] == payment_mined_event]
    assert len(payment_messages) == 1, "we should have received one payment received message"

    payment_data = payment_messages[0]
    assert is_0x_prefixed(payment_data["transaction"])
    assert is_0x_prefixed(payment_data["token"])
    assert (
        Decimal(payment_data["amount"]) == checkout.order.amount
    ), "payment amount does not match"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_checkout_receives_transaction_broadcast_notification(
    checkout, erc20_blockchain_checkout_payment
):
    communicator = WebsocketCommunicator(application, f"checkout/{checkout.id}")

    ok, protocol_or_error = await communicator.connect()
    assert ok, "Failed to connect"

    order = checkout.order
    account = await sync_to_async(deposit_account)(order)
    tx_params = await sync_to_async(deposit_transaction_params)(order)
    tx_data = deposit_tx_data(tx_params)

    await sync_to_async(handlers.on_incoming_transfer_broadcast_notify_open_checkouts)(
        sender=tx_data.__class__,
        account=account,
        amount=order.as_token_amount,
        transaction_data=tx_data,
    )

    messages = []
    while not await communicator.receive_nothing(timeout=0.25):
        messages.append(await communicator.receive_json_from())

    await communicator.disconnect()

    assert len(messages) != 0, "we should have received something here"
    payment_sent_event = Events.DEPOSIT_BROADCAST.value

    payment_messages = [msg for msg in messages if msg["event"] == payment_sent_event]
    assert len(payment_messages) == 1, "we should have received one payment sent message"

    payment_data = payment_messages[0]
    assert is_0x_prefixed(payment_data["transaction"])
    assert is_0x_prefixed(payment_data["token"])
    assert (
        Decimal(payment_data["amount"]) == checkout.order.amount
    ), "payment amount does not match"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_checkout_receives_confirmation_notification(
    checkout, erc20_blockchain_checkout_payment, treasury
):
    communicator = WebsocketCommunicator(application, f"checkout/{checkout.id}")

    ok, protocol_or_error = await communicator.connect()
    assert ok, "Failed to connect"

    tx_block_number = erc20_blockchain_checkout_payment.transaction.block.number
    confirmation_block_number = tx_block_number + app_settings.Blockchain.minimum_confirmations

    block = await sync_to_async(BlockFactory)(number=confirmation_block_number)
    block.chain.highest_block = confirmation_block_number

    await sync_to_async(handlers.on_chain_updated_check_payment_confirmations)(
        sender=Chain, instance=block.chain
    )

    messages = []
    while not await communicator.receive_nothing(timeout=0.25):
        messages.append(await communicator.receive_json_from())

    await communicator.disconnect()

    assert len(messages) != 0, "we should have received something here"
    payment_confirmed_event = Events.DEPOSIT_CONFIRMED.value

    payment_messages = [msg for msg in messages if msg["event"] == payment_confirmed_event]
    assert len(payment_messages) == 1, "we should have received one payment confirmed message"


__all__ = [
    "test_session_receives_token_deposit_received",
    "test_checkout_receives_transaction_mined_notification",
    "test_checkout_receives_transaction_broadcast_notification",
    "test_checkout_receives_confirmation_notification",
]
