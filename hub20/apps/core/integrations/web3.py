import asyncio
import logging
from functools import wraps

from asgiref.sync import sync_to_async
from web3 import Web3

from hub20.apps.blockchain.client import get_web3, wait_for_connection
from hub20.apps.blockchain.models import BaseEthereumAccount
from hub20.apps.core.models import BlockchainPaymentRoute
from hub20.apps.ethereum_money.abi import EIP20_ABI
from hub20.apps.ethereum_money.client import (
    process_incoming_erc20_transfer_event,
    process_pending_incoming_erc20_transfer_event,
)
from hub20.apps.ethereum_money.models import EthereumToken

logger = logging.getLogger(__name__)


def deposit_filter_args(route):
    return dict(
        fromBlock=route.start_block_number,
        toBlock=route.expiration_block_number,
        argument_filters={"_to": route.account.address},
    )


def pending_deposit_filter_args(route):
    return dict(
        fromBlock=route.start_block_number,
        toBlock="pending",
        argument_filters={"_to": route.account.address},
    )


def blockchain_deposits_handler(abi, event, deposit_filter_args):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(*args, **kw):
            w3: Web3 = get_web3()
            wait_for_connection(w3=w3)

            while True:
                try:
                    wait_for_connection(w3=w3)
                    block_number = w3.eth.block_number

                    open_routes = await sync_to_async(list)(
                        BlockchainPaymentRoute.objects.available(
                            block_number=block_number
                        ).select_related("deposit", "deposit__currency", "account")
                    )

                    for route in open_routes:
                        token = route.deposit.currency

                        # We are only concerned here about ERC20
                        # tokens. ETH transfers are detected directly
                        # by the blockchain listeners
                        if not token.is_ERC20:
                            continue

                        contract = w3.eth.contract(abi=abi, address=token.address)
                        filter_params = deposit_filter_args(route)

                        event_type = getattr(contract.events, event)
                        try:
                            event_filter = await sync_to_async(event_type.createFilter)(
                                **filter_params
                            )
                            for event_entry in event_filter.get_all_entries():
                                await sync_to_async(handler)(
                                    w3=w3, token=token, account=route.account, event=event_entry
                                )

                        except ValueError:
                            logger.warning(f"Can not get {event} filter with {filter_params}")
                            return
                except Exception as exc:
                    logger.exception(f"Error on {handler.__name__}: {exc}")
                finally:
                    try:
                        await asyncio.sleep(1)
                    except RuntimeError:
                        pass

        return wrapper

    return decorator


@blockchain_deposits_handler(
    abi=EIP20_ABI, event="Transfer", deposit_filter_args=deposit_filter_args
)
def handle_token_deposits(w3: Web3, token: EthereumToken, account: BaseEthereumAccount, event):
    process_incoming_erc20_transfer_event(w3=w3, token=token, account=account, event=event)


@blockchain_deposits_handler(
    abi=EIP20_ABI,
    event="Transfer",
    deposit_filter_args=pending_deposit_filter_args,
)
def handle_pending_token_deposits(
    w3: Web3, token: EthereumToken, account: BaseEthereumAccount, event
):
    process_pending_incoming_erc20_transfer_event(w3=w3, token=token, account=account, event=event)
