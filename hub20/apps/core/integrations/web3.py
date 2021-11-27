import asyncio
import logging

import celery_pubsub

from asgiref.sync import sync_to_async

from hub20.apps.blockchain.client import make_web3
from hub20.apps.core.models import BlockchainPaymentRoute
from hub20.apps.ethereum_money.abi import EIP20_ABI

from hub20.apps.ethereum_money.models import EthereumToken

logger = logging.getLogger(__name__)


async def pending_token_transfers():
    logger.debug("Checking for pending token transfers")
    while True:
        open_routes = await sync_to_async(list)(
            BlockchainPaymentRoute.objects.open().select_related(
                "deposit", "deposit__currency", "deposit__currency__chain", "account"
            )
        )

        for route in open_routes:
            logger.info(f"Checking for pending token transfers for payment {route.deposit_id}")
            token: EthereumToken = route.deposit.currency

            # We are only concerned here about ERC20
            # tokens. ETH transfers are detected directly
            # by the blockchain listeners
            if not token.is_ERC20:
                continue

            w3 = make_web3(provider_url=token.chain.provider_url)
            contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)

            try:
                for transfer_event in contract.events.Transfer().getLogs(
                    {"fromBlock": "pending", "argument_filters": {"_to": route.account.address}}
                ):
                    tx_data = w3.eth.get_transaction(transfer_event.transactionHash)
                    await sync_to_async(celery_pubsub.publish)(
                        "blockchain.event.pending",
                        chain_id=w3.eth.chain_id,
                        transaction_data=tx_data,
                        event=transfer_event,
                    )
            except ValueError:
                logger.warning(f"Can not get transfer logs from {token.chain.provider_hostname}")
        else:
            await asyncio.sleep(1)
