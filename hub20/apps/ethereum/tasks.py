import logging
from typing import Dict

import celery_pubsub
from celery import shared_task
from web3.datastructures import AttributeDict

from hub20.apps.core.tasks import broadcast_event

from .abi.tokens import EIP20_ABI
from .constants import Events
from .models import BaseWallet, Block, WalletBalanceRecord, Web3Provider
from .signals import block_sealed

logger = logging.getLogger(__name__)


@shared_task
def notify_block_created(chain_id, block_data):
    logger.debug(f"Broadcast event of new block on #{chain_id}")
    block_data = AttributeDict(block_data)
    broadcast_event(
        event=Events.BLOCK_CREATED.value,
        chain_id=chain_id,
        hash=block_data.hash,
        number=block_data.number,
        timestamp=block_data.timestamp,
    )


# Tasks that are setup to subscribe and handle events generated by the event streams
@shared_task
def notify_new_block(chain_id, block_data: Dict, provider_url):
    block_data = AttributeDict(block_data)
    logger.debug(f"Sending notification of new block on chain #{chain_id}")
    block_sealed.send(sender=Block, chain_id=chain_id, block_data=block_data)


@shared_task
def update_wallet_erc20_token_balances():
    for provider in Web3Provider.available.all():
        try:
            current_block = provider.w3.eth.block_number
        except Exception:
            logger.exception(f"Failed to get block info on {provider}")
            continue

        for wallet in BaseWallet.objects.all():
            for token in provider.chain.tokens.all():
                last_recorded_balance = wallet.current_balance(token)
                last_recorded_block = last_recorded_balance and last_recorded_balance.block

                if last_recorded_block is None or last_recorded_block.number < current_block:
                    try:
                        contract = provider.w3.eth.contract(abi=EIP20_ABI, address=token.address)
                        current_balance = contract.functions.balanceOf(wallet.address).call()
                        balance_amount = token.from_wei(current_balance)
                        block_data = provider.w3.eth.get_block(current_block)
                        block = Block.make(block_data=block_data, chain_id=token.chain_id)

                        WalletBalanceRecord.objects.create(
                            wallet=wallet,
                            currency=balance_amount.currency,
                            amount=balance_amount.amount,
                            block=block,
                        )
                    except Exception:
                        logger.exception(f"Failed to get {token} balance for {wallet.address}")


@shared_task
def update_wallet_native_token_balances():
    for provider in Web3Provider.available.all():
        try:
            current_block = provider.w3.eth.block_number
        except Exception:
            logger.exception(f"Failed to get block info on {provider}")
            continue

        for wallet in BaseWallet.objects.all():
            token = provider.chain.native_token
            last_recorded_balance = wallet.current_balance(token)
            last_recorded_block = last_recorded_balance and last_recorded_balance.block

            if last_recorded_block is None or last_recorded_block.number < current_block:
                try:
                    block_data = provider.w3.eth.get_block(current_block)
                    balance = token.from_wei(
                        provider.w3.eth.get_balance(
                            wallet.address, block_identifier=block_data.hash.hex()
                        )
                    )

                    block = Block.make(block_data=block_data, chain_id=token.chain_id)

                    WalletBalanceRecord.objects.create(
                        wallet=wallet,
                        currency=balance.currency,
                        amount=balance.amount,
                        block=block,
                    )

                except Exception:
                    logger.exception(f"Failed to get {token} balance for {wallet.address}")


celery_pubsub.subscribe("blockchain.mined.block", notify_new_block)
