import asyncio
import logging

import celery_pubsub
from asgiref.sync import sync_to_async
from django.core.cache import cache

from hub20.apps.blockchain.client import BLOCK_CREATION_INTERVAL, make_web3
from hub20.apps.blockchain.models import Web3Provider
from hub20.apps.core.models import BlockchainPaymentRoute
from hub20.apps.ethereum_money.abi import EIP20_ABI
from hub20.apps.ethereum_money.models import EthereumToken

logger = logging.getLogger(__name__)


async def process_transfers_in_open_routes():
    CACHE_KEY = "TRANSACTIONS_FOR_OPEN_ROUTES"

    logger.debug("Checking for token transfers in open routes")
    while True:
        open_routes = await sync_to_async(list)(
            BlockchainPaymentRoute.objects.open().select_related(
                "deposit",
                "deposit__currency",
                "deposit__currency__chain",
                "account",
            )
        )

        for route in open_routes:
            logger.info(f"Checking for token transfers for payment {route.deposit_id}")
            token: EthereumToken = route.deposit.currency

            # We are only concerned here about ERC20 tokens. Native token
            # transfers are detected directly by the blockchain listeners
            if not token.is_ERC20:
                continue

            provider = await sync_to_async(Web3Provider.active.filter(chain=token.chain).first)()

            if not provider:
                logger.warning(
                    f"Route {route} is open but not provider available to check for payments"
                )
                continue

            w3 = make_web3(provider=provider)
            contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)

            event_filter = contract.events.Transfer().createFilter(
                fromBlock=route.start_block_number,
                toBlock=route.expiration_block_number,
                argument_filters={"_to": route.account.address},
            )

            try:
                for transfer_event in event_filter.get_all_entries():
                    tx_hash = transfer_event.transactionHash.hex()

                    key = f"{CACHE_KEY}:{tx_hash}"

                    if await sync_to_async(cache.get)(key):
                        logger.debug(f"Transfer event in tx {tx_hash} has already been published")

                        continue

                    logger.debug(f"Publishing transfer event from tx {tx_hash}")
                    await sync_to_async(celery_pubsub.publish)(
                        "blockchain.event.token_transfer.mined",
                        chain_id=w3.eth.chain_id,
                        event_data=transfer_event,
                        provider_url=provider.url,
                    )
                    await sync_to_async(cache.set)(key, True, timeout=BLOCK_CREATION_INTERVAL * 2)
            except ValueError as exc:
                logger.warning(f"Can not get transfer logs from {provider.hostname}: {exc}")
        else:
            await asyncio.sleep(1)


async def process_pending_transfers_in_open_routes():
    CACHE_KEY = "PENDING_TRANSACTIONS_FOR_OPEN_ROUTES"

    logger.debug("Checking for pending token transfers in open routes")
    while True:
        open_routes = await sync_to_async(list)(
            BlockchainPaymentRoute.objects.open().select_related(
                "deposit",
                "deposit__currency",
                "deposit__currency__chain",
                "account",
            )
        )

        for route in open_routes:
            logger.info(f"Checking for pending token transfers for payment {route.deposit_id}")
            token: EthereumToken = route.deposit.currency

            # We are only concerned here about ERC20 tokens. Native token
            # transfers are detected directly by the blockchain listeners
            if not token.is_ERC20:
                continue

            provider = await sync_to_async(Web3Provider.active.filter(chain=token.chain).first)()

            if not provider:
                logger.warning(
                    f"Route {route} is open but not provider available to check for payments"
                )
                continue

            w3 = make_web3(provider=provider)
            contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)

            event_filter = contract.events.Transfer().createFilter(
                fromBlock="pending",
                toBlock="pending",
                argument_filters={"_to": route.account.address},
            )

            try:
                for transfer_event in event_filter.get_all_entries():
                    tx_hash = transfer_event.transactionHash.hex()

                    key = f"{CACHE_KEY}:{tx_hash}"

                    if await sync_to_async(cache.get)(key):
                        logger.debug(f"Broadcast of tx {tx_hash} has already been notified")
                        continue

                    await sync_to_async(celery_pubsub.publish)(
                        "blockchain.event.token_transfer.broadcast",
                        chain_id=w3.eth.chain_id,
                        event_data=transfer_event,
                        provider_url=provider.url,
                    )
                    await sync_to_async(cache.set)(key, True, timeout=BLOCK_CREATION_INTERVAL * 2)
            except ValueError as exc:
                logger.warning(f"Can not get transfer logs from {provider.hostname}: {exc}")
        else:
            await asyncio.sleep(1)
