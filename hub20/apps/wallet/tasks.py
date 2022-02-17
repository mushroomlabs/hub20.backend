import logging

import celery_pubsub
from celery import shared_task

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import Block, Chain, Web3Provider
from hub20.apps.ethereum_money.abi import EIP20_ABI
from hub20.apps.ethereum_money.models import EthereumToken

from .models import Wallet, WalletBalanceRecord

logger = logging.getLogger(__name__)


def _get_native_token_balance(wallet: Wallet, token: EthereumToken, block_data):

    try:
        assert not token.is_ERC20, f"{token} is an ERC20-token"
        provider = Web3Provider.available.get(chain_id=token.chain_id)
    except AssertionError as exc:
        logger.warning(str(exc))
        return
    except Web3Provider.DoesNotExist:
        logger.warning(f"Can not get balance for {wallet}: no provider available")
        return

    w3 = make_web3(provider=provider)

    balance = token.from_wei(
        w3.eth.get_balance(wallet.address, block_identifier=block_data.hash.hex())
    )

    block = Block.make(block_data=block_data, chain_id=token.chain_id)

    WalletBalanceRecord.objects.create(
        wallet=wallet,
        currency=balance.currency,
        amount=balance.amount,
        block=block,
    )


def _get_erc20_token_balance(wallet: Wallet, token: EthereumToken, block_data):
    try:
        provider = Web3Provider.available.get(chain_id=token.chain_id)
    except Web3Provider.DoesNotExist:
        logger.warning(f"Can not get balance for {wallet}: no provider available")
        return

    current_record = wallet.current_balance(token)
    current_block = current_record and current_record.block

    w3 = make_web3(provider=provider)

    # Unlike native tokens, we can only get the current balance for
    # ERC20 tokens - i.e, we can not select at block-time. So we need to
    if current_block is None or current_block.number < block_data.number:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        balance = token.from_wei(contract.functions.balanceOf(wallet.address).call())
        block = Block.make(block_data=block_data, chain_id=token.chain_id)

        WalletBalanceRecord.objects.create(
            wallet=wallet,
            currency=balance.currency,
            amount=balance.amount,
            block=block,
        )


@shared_task
def update_all_wallet_balances():
    for provider in Web3Provider.available.all():
        w3 = make_web3(provider=provider)
        chain_id = w3.eth.chain_id
        block_data = w3.eth.get_block(w3.eth.block_number, full_transactions=True)
        for wallet in Wallet.objects.all():
            for token in EthereumToken.objects.filter(chain_id=chain_id):
                action = _get_erc20_token_balance if token.is_ERC20 else _get_native_token_balance
                action(wallet=wallet, token=token, block_data=block_data)


@shared_task
def update_wallet_token_balances(chain_id, event_data, provider_url):
    token_address = event_data.address
    token = EthereumToken.objects.filter(chain_id=chain_id, address=token_address).first()

    if not token:
        return

    sender = event_data.args._from
    recipient = event_data.args._to

    affected_wallets = Wallet.objects.filter(address__in=[sender, recipient])

    if not affected_wallets.exists():
        return

    provider = Web3Provider.objects.get(url=provider_url)
    w3 = make_web3(provider=provider)

    block_data = w3.eth.get_block(event_data.blockNumber, full_transactions=True)

    amount = token.from_wei(event_data.args._value)

    for wallet in affected_wallets:
        _get_erc20_token_balance(wallet=wallet, token=amount.currency, block_data=block_data)


@shared_task
def update_wallet_native_token_balances(chain_id, block_data, provider_url):
    addresses = Wallet.objects.values_list("address", flat=True)

    txs = [
        t
        for t in block_data["transactions"]
        if t.value > 0 and (t["to"] in addresses or t["from"] in addresses)
    ]

    if not txs:
        return

    try:
        chain = Chain.active.get(id=chain_id)
    except Chain.DoesNotExist:
        logger.warning(f"Chain {chain_id} not found")
        return

    native_token = EthereumToken.make_native(chain=chain)

    for transaction_data in txs:
        sender = transaction_data["from"]
        recipient = transaction_data["to"]

        affected_wallets = Wallet.objects.filter(address__in=[sender, recipient])

        if not affected_wallets.exists():
            return

        for wallet in affected_wallets:
            _get_native_token_balance(wallet=wallet, token=native_token, block_data=block_data)


celery_pubsub.subscribe("blockchain.event.token_transfer.mined", update_wallet_token_balances)
celery_pubsub.subscribe("blockchain.mined.block", update_wallet_native_token_balances)
