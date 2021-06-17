import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from asgiref.sync import sync_to_async
from eth_utils import to_checksum_address
from ethereum.abi import ContractTranslator
from web3 import Web3
from web3.exceptions import TimeExhausted, TransactionNotFound

from hub20.apps.blockchain.client import (
    BLOCK_CREATION_INTERVAL,
    BLOCK_SCAN_RANGE,
    get_transaction_by_hash,
    get_web3,
    wait_for_connection,
)
from hub20.apps.blockchain.models import BaseEthereumAccount, Block, Chain, Transaction
from hub20.apps.blockchain.typing import Address, EthereumAccount_T
from hub20.apps.ethereum_money import get_ethereum_account_model

from .abi import EIP20_ABI, ERC223_ABI
from .app_settings import TRANSFER_GAS_LIMIT
from .models import EthereumToken, EthereumTokenAmount
from .signals import (
    incoming_transfer_broadcast,
    incoming_transfer_mined,
    outgoing_transfer_broadcast,
    outgoing_transfer_mined,
)

logger = logging.getLogger(__name__)
EthereumAccount = get_ethereum_account_model()


class TokenEventFilterRegistry:
    _REGISTRY: Dict[Tuple[Address, Address], Any] = {}

    def __init__(self, w3: Web3, token: EthereumToken, account: EthereumAccount_T):
        self.token = token
        self.erc20_contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        self.erc223_contract = w3.eth.contract(abi=ERC223_ABI, address=token.address)

        self.approvals = self.erc20_contract.events.Approval.createFilter(
            fromBlock="latest", argument_filters={"_owner": account.address}
        )

        self.incoming_transfer = self.erc20_contract.events.Transfer.createFilter(
            fromBlock="latest", argument_filters={"_to": account.address}
        )

        self.outgoing_transfer = self.erc20_contract.events.Transfer.createFilter(
            fromBlock="latest", argument_filters={"_from": account.address}
        )

        self.minter = self.erc223_contract.events.Minted.createFilter(
            fromBlock="latest", argument_filters={"_to": account.address}
        )

    @classmethod
    def get(cls, w3: Web3, token: EthereumToken, account: EthereumAccount_T):
        key = (token.address, account.address)
        if key in cls._REGISTRY:
            return cls._REGISTRY[key]
        else:
            event_filter = cls(w3=w3, token=token, account=account)
            cls._REGISTRY[key] = event_filter
            return event_filter


def _decode_transfer_arguments(w3: Web3, token: EthereumToken, tx_data):
    try:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        fn, args = contract.decode_function_input(tx_data.input)

        # TODO: is this really the best way to identify the transaction as a value transfer?
        transfer_idenfifier = contract.functions.transfer.function_identifier
        if not transfer_idenfifier == fn.function_identifier:
            return None

        return args
    except ValueError:
        return None
    except Exception as exc:
        logger.exception(exc)


def encode_transfer_data(recipient_address, amount: EthereumTokenAmount):
    translator = ContractTranslator(EIP20_ABI)
    encoded_data = translator.encode_function_call("transfer", (recipient_address, amount.as_wei))
    return f"0x{encoded_data.hex()}"


def make_token_approval_filter(w3: Web3, token: EthereumToken, account: EthereumAccount_T):
    starting_block = token.chain.highest_block
    contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
    return contract.events.Approval.createFilter(
        fromBlock=starting_block, argument_filters={"_owner": account.address}
    )


def get_transfer_value_by_tx_data(
    w3: Web3, token: EthereumToken, tx_data
) -> Optional[EthereumTokenAmount]:
    if not token.is_ERC20:
        return token.from_wei(tx_data.value)

    args = _decode_transfer_arguments(w3, token, tx_data)
    if args is not None:
        return token.from_wei(args["_value"])


def get_transfer_recipient_by_tx_data(w3: Web3, token: EthereumToken, tx_data):
    args = _decode_transfer_arguments(w3, token, tx_data)
    if args is not None:
        return args["_to"]


def get_transfer_recipient_by_receipt(w3: Web3, token: EthereumToken, tx_receipt):
    contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
    tx_logs = contract.events.Transfer().processReceipt(tx_receipt)
    assert len(tx_logs) == 1, "There should be only one log entry on transfer function"

    return tx_logs[0].args["_to"]


def get_max_fee(w3: Web3) -> EthereumTokenAmount:
    chain = Chain.make(chain_id=int(w3.net.version))
    ETH = EthereumToken.ETH(chain=chain)

    gas_price = w3.eth.generateGasPrice()
    return ETH.from_wei(TRANSFER_GAS_LIMIT * gas_price)


def get_account_balance(w3: Web3, token: EthereumToken, address: Address) -> EthereumTokenAmount:
    if token.is_ERC20:
        contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
        return token.from_wei(contract.functions.balanceOf(address).call())
    else:
        return token.from_wei(w3.eth.getBalance(address))


def get_token_information(w3: Web3, address):
    contract = w3.eth.contract(abi=EIP20_ABI, address=to_checksum_address(address))
    return {
        "name": contract.functions.name().call(),
        "code": contract.functions.symbol().call(),
        "decimals": contract.functions.decimals().call(),
    }


def make_token(w3: Web3, address) -> EthereumToken:
    token_data = get_token_information(w3=w3, address=address)
    chain = Chain.make(chain_id=int(w3.net.version))
    return EthereumToken.make(chain=chain, address=address, **token_data)


def index_account_erc20_transfers(
    w3: Web3, account: EthereumAccount_T, token: EthereumToken, starting_block: int, end_block: int
):
    logger.debug(
        "Checking blocks {}-{} for {} transfers from {}".format(
            starting_block, end_block, token.code, account.address
        )
    )

    token_contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
    incoming_transfer_filter = token_contract.events.Transfer.createFilter(
        fromBlock=starting_block, toBlock=end_block, argument_filters={"_to": account.address}
    )
    outgoing_transfer_filter = token_contract.events.Transfer.createFilter(
        fromBlock=starting_block, toBlock=end_block, argument_filters={"_from": account.address}
    )

    for event in incoming_transfer_filter.get_all_entries():
        process_incoming_erc20_transfer_event(w3=w3, token=token, account=account, event=event)

    for event in outgoing_transfer_filter.get_all_entries():
        process_outgoing_erc20_transfer_event(w3=w3, token=token, account=account, event=event)


def index_account_erc223_transactions(
    w3: Web3, account: EthereumAccount_T, token: EthereumToken, starting_block: int, end_block: int
):
    logger.debug(
        "Checking blocks {}-{} for {} tokens minted for {}".format(
            starting_block, end_block, token.code, account.address
        )
    )

    token_contract = w3.eth.contract(abi=ERC223_ABI, address=token.address)
    token_mint_filter = token_contract.events.Minted.createFilter(
        fromBlock=starting_block, toBlock=end_block, argument_filters={"_to": account.address}
    )
    for event in token_mint_filter.get_all_entries():
        process_erc223_token_mint_event(w3=w3, token=token, account=account, event=event)


def index_account_erc20_approvals(
    w3: Web3, account: EthereumAccount_T, token: EthereumToken, starting_block: int, end_block: int
):
    logger.debug(
        "Checking blocks {}-{} for {} approvals from {}".format(
            starting_block, end_block, token.code, account.address
        )
    )

    token_contract = w3.eth.contract(abi=EIP20_ABI, address=token.address)
    approval_filter = token_contract.events.Approval.createFilter(
        fromBlock=starting_block, toBlock=end_block, argument_filters={"_owner": account.address}
    )
    for event in approval_filter.get_all_entries():
        transaction = get_transaction_by_hash(w3=w3, transaction_hash=event.transactionHash)
        if transaction:
            account.transactions.add(transaction)


def process_pending_transfers(w3: Web3, chain: Chain, tx_filter):
    wait_for_connection(w3)
    chain.refresh_from_db()

    # Convert the querysets to lists of addresses
    accounts_by_addresses = {account.address: account for account in EthereumAccount.objects.all()}
    tokens_by_address = {
        token.address: token for token in EthereumToken.ERC20tokens.filter(chain=chain)
    }
    ETH = EthereumToken.ETH(chain=chain)

    pending_txs = [entry.hex() for entry in tx_filter.get_new_entries()]
    recorded_txs = tuple(
        Transaction.objects.filter(hash__in=pending_txs).values_list("hash", flat=True)
    )
    for tx_hash in set(pending_txs) - set(recorded_txs):
        try:
            tx_data = w3.eth.getTransaction(tx_hash)
            token = tokens_by_address.get(tx_data.to)
            if token:
                recipient_address = get_transfer_recipient_by_tx_data(w3, token, tx_data)
                amount = get_transfer_value_by_tx_data(w3, token, tx_data)
            elif tx_data.to in accounts_by_addresses:
                recipient_address = tx_data.to
                amount = ETH.from_wei(tx_data.value)
            else:
                continue

            recipient_account = accounts_by_addresses.get(recipient_address)
            if recipient_account is not None and amount is not None:
                logger.info(f"Processing pending Tx {tx_hash}")
                incoming_transfer_broadcast.send(
                    sender=EthereumToken,
                    account=recipient_account,
                    amount=amount,
                    transaction_hash=tx_hash,
                )

            sender_account = accounts_by_addresses.get(tx_data["from"])
            if sender_account is not None and amount is not None:
                outgoing_transfer_broadcast.send(
                    sender=EthereumToken,
                    account=sender_account,
                    amount=amount,
                    transaction_hash=tx_hash,
                )
        except TimeoutError:
            logger.error(f"Failed request to get or check {tx_hash}")
        except TransactionNotFound:
            logger.info(f"Tx {tx_hash} has not yet been mined")
        except ValueError as exc:
            logger.exception(exc)
        except Exception as exc:
            logger.exception(exc)


def process_latest_transfers(w3: Web3, chain: Chain, block_filter):
    wait_for_connection(w3)
    chain.refresh_from_db()

    accounts_by_address = {a.address: a for a in BaseEthereumAccount.objects.all()}
    tokens = EthereumToken.ERC20tokens.filter(chain=chain).select_related("chain")
    tokens_by_address = {token.address: token for token in tokens}
    ETH = EthereumToken.ETH(chain=chain)

    for block_hash in block_filter.get_new_entries():
        block_data = w3.eth.get_block(block_hash.hex(), full_transactions=True)

        logger.info(f"Checking block {block_hash.hex()} for relevant transfers")
        for tx_data in block_data.transactions:
            tx_hash = tx_data.hash
            logger.info(f"Checking Tx {tx_hash.hex()}")

            token = tokens_by_address.get(tx_data.to)
            sender_address = tx_data["from"]
            sender_account = accounts_by_address.get(sender_address)

            if token:
                recipient_address = get_transfer_recipient_by_tx_data(w3, token, tx_data)
                transfer_amount = get_transfer_value_by_tx_data(
                    w3=w3, token=token, tx_data=tx_data
                )
            else:
                recipient_address = tx_data.to
                transfer_amount = ETH.from_wei(tx_data.value)

            recipient_account = accounts_by_address.get(recipient_address)

            if not any((sender_account, recipient_account)):
                continue

            try:
                logger.info(f"Saving tx {tx_hash.hex()}: {sender_address} -> {recipient_address}")
                tx_receipt = w3.eth.waitForTransactionReceipt(tx_data.hash)
                block = Block.make(block_data, chain_id=chain.id)
                tx = Transaction.make(tx_data=tx_data, tx_receipt=tx_receipt, block=block)

            except TimeExhausted:
                logger.warning(f"Timeout when waiting for receipt of tx {tx_hash.hex()}")

            if sender_account:
                outgoing_transfer_mined.send(
                    sender=Transaction,
                    account=sender_account,
                    transaction=tx,
                    amount=transfer_amount,
                    address=recipient_address,
                )

            if recipient_account:
                incoming_transfer_mined.send(
                    sender=Transaction,
                    account=sender_account,
                    transaction=tx,
                    amount=transfer_amount,
                )


def process_erc20_approval_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    transaction = get_transaction_by_hash(w3=w3, transaction_hash=event.transactionHash)
    if transaction:
        account.transactions.add(transaction)


def process_incoming_erc20_transfer_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    amount = token.from_wei(event["args"]["_value"])
    transaction = get_transaction_by_hash(w3=w3, transaction_hash=event.transactionHash)
    if transaction:
        account.transactions.add(transaction)
        incoming_transfer_mined.send(
            sender=Transaction,
            account=account,
            transaction=transaction,
            amount=amount,
            address=event["args"]["_from"],
        )


def process_outgoing_erc20_transfer_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    amount = token.from_wei(event["args"]["_value"])
    transaction = get_transaction_by_hash(w3=w3, transaction_hash=event.transactionHash)
    if transaction:
        account.transactions.add(transaction)
        outgoing_transfer_mined.send(
            sender=Transaction,
            account=account,
            transaction=transaction,
            amount=amount,
            address=event["args"]["_to"],
        )


def process_erc223_token_mint_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    amount = token.from_wei(event["args"]["_num"])
    transaction = get_transaction_by_hash(w3=w3, transaction_hash=event.transactionHash)
    if transaction:
        account.transactions.add(transaction)
        incoming_transfer_mined.send(
            sender=Transaction,
            account=account,
            transaction=transaction,
            amount=amount,
            address=token.address,
        )


class EthereumClient:
    def __init__(self, account: EthereumAccount_T, w3: Optional[Web3] = None) -> None:
        self.account = account
        self.w3 = w3 or get_web3()

    def build_transfer_transaction(self, recipient, amount: EthereumTokenAmount):
        token = amount.currency
        chain_id = int(self.w3.net.version)
        message = f"Connected to network {chain_id}, token {token.code} is on {token.chain_id}"
        assert token.chain_id == chain_id, message

        transaction_params = {
            "chainId": chain_id,
            "nonce": self.w3.eth.getTransactionCount(self.account.address),
            "gasPrice": self.w3.eth.generateGasPrice(),
            "gas": TRANSFER_GAS_LIMIT,
            "from": self.account.address,
        }

        if token.is_ERC20:
            transaction_params.update(
                {"to": token.address, "value": 0, "data": encode_transfer_data(recipient, amount)}
            )
        else:
            transaction_params.update({"to": recipient, "value": amount.as_wei})
        return transaction_params

    def transfer(self, amount: EthereumTokenAmount, address, *args, **kw):
        transaction_data = self.build_transfer_transaction(recipient=address, amount=amount)
        signed_tx = self.sign_transaction(transaction_data=transaction_data)
        return self.w3.eth.sendRawTransaction(signed_tx.rawTransaction)

    def sign_transaction(self, transaction_data, *args, **kw):
        if not hasattr(self.account, "private_key"):
            raise NotImplementedError("Can not sign transaction without the private key")
        return self.w3.eth.account.signTransaction(transaction_data, self.account.private_key)

    def get_balance(self, token: EthereumToken):
        return get_account_balance(w3=self.w3, token=token, address=self.account.address)

    @classmethod
    def select_for_transfer(cls, amount: EthereumTokenAmount, **kw) -> Optional[EthereumAccount_T]:
        w3 = kw.pop("w3", get_web3())

        transfer_fee: EthereumTokenAmount = cls.estimate_transfer_fees(w3=w3)
        assert transfer_fee.is_ETH

        ETH = transfer_fee.currency

        accounts = EthereumAccount.objects.all().order_by("?")

        if amount.is_ETH:
            amount += transfer_fee

        for account in accounts:
            get_balance = lambda t: get_account_balance(w3=w3, token=t, address=account.address)

            eth_balance = get_balance(ETH)
            token_balance = eth_balance if amount.is_ETH else get_balance(amount.currency)

            if eth_balance >= transfer_fee and token_balance >= amount:
                return cls(account)
        return None

    @classmethod
    def estimate_transfer_fees(cls, *args, **kw) -> EthereumTokenAmount:
        w3 = kw.pop("w3", get_web3())
        return get_max_fee(w3=w3)


async def listen_eth_transfers(w3: Web3, **kw):
    await sync_to_async(wait_for_connection)(w3)
    block_filter = w3.eth.filter("latest")
    chain_id = int(w3.net.version)

    while True:
        chain = await sync_to_async(Chain.make)(chain_id=chain_id)
        accounts = await sync_to_async(list)(BaseEthereumAccount.objects.all())
        ETH = await sync_to_async(EthereumToken.ETH)(chain=chain)

        accounts_by_address = {account.address: account for account in accounts}

        for block_hash in block_filter.get_new_entries():
            block_data = w3.eth.get_block(block_hash.hex(), full_transactions=True)

            logger.info(f"Checking block {block_hash.hex()} for relevant ETH transfers")

            for tx_data in block_data.transactions:
                sender_address = tx_data["from"]
                recipient_address = tx_data.to

                is_ETH_transfer = tx_data.value != 0
                tx_hash = tx_data.hash

                if not is_ETH_transfer:
                    continue

                amount = ETH.from_wei(tx_data.value)

                if sender_address in accounts_by_address.keys():
                    account = accounts_by_address.get(sender_address)
                    transaction = get_transaction_by_hash(w3=w3, transaction_hash=tx_hash)
                    if transaction:
                        account.transactions.add(transaction)
                        outgoing_transfer_mined.send(
                            sender=Transaction,
                            account=account,
                            token=ETH,
                            amount=amount,
                            transaction=transaction,
                            address=recipient_address,
                        )

                elif recipient_address in accounts_by_address.keys():
                    account = accounts_by_address.get(recipient_address)
                    transaction = get_transaction_by_hash(w3=w3, transaction_hash=tx_hash)
                    if transaction:
                        account.transactions.add(transaction)
                        incoming_transfer_mined.send(
                            sender=Transaction,
                            account=account,
                            token=ETH,
                            amount=amount,
                            transaction=transaction,
                            address=sender_address,
                        )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def listen_erc20_transfers(w3: Web3, **kw):
    await sync_to_async(wait_for_connection)(w3)

    chain_id = int(w3.net.version)
    chain = await sync_to_async(Chain.make)(chain_id=chain_id)

    while True:
        await sync_to_async(chain.refresh_from_db)()
        accounts = await sync_to_async(list)(BaseEthereumAccount.objects.all())
        tokens = await sync_to_async(list)(EthereumToken.ERC20tokens.all())

        for token in tokens:
            for account in accounts:
                event_filter = TokenEventFilterRegistry.get(w3=w3, token=token, account=account)
                incoming_txs = event_filter.incoming_transfer.get_new_entries()
                logger.debug(f"Got {len(incoming_txs)} {token.code} txs to {account.address}")
                for event in incoming_txs:
                    await sync_to_async(process_incoming_erc20_transfer_event)(
                        w3=w3, account=account, token=token, event=event
                    )

                outgoing_txs = event_filter.outgoing_transfer.get_new_entries()
                logger.debug(f"Got {len(outgoing_txs)} {token.code} txs from {account.address}")
                for event in outgoing_txs:
                    await sync_to_async(process_outgoing_erc20_transfer_event)(
                        w3=w3, account=account, token=token, event=event
                    )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def listen_erc20_approvals(w3: Web3, **kw):
    await sync_to_async(wait_for_connection)(w3)

    chain_id = int(w3.net.version)
    chain = await sync_to_async(Chain.make)(chain_id=chain_id)

    while True:
        await sync_to_async(chain.refresh_from_db)()
        accounts = await sync_to_async(list)(BaseEthereumAccount.objects.all())
        tokens = await sync_to_async(list)(EthereumToken.ERC20tokens.all())

        for token in tokens:
            for account in accounts:
                event_filter = TokenEventFilterRegistry.get(w3=w3, token=token, account=account)
                approval_txs = event_filter.approvals.get_new_entries()
                logger.debug(
                    f"Got {len(approval_txs)} {token.code} approval from {account.address}"
                )
                for event in approval_txs:
                    await sync_to_async(process_erc20_approval_event)(
                        w3=w3, account=account, token=token, event=event
                    )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def listen_erc223_mint(w3: Web3, **kw):
    await sync_to_async(wait_for_connection)(w3)

    chain_id = int(w3.net.version)
    chain = await sync_to_async(Chain.make)(chain_id=chain_id)

    while True:
        await sync_to_async(chain.refresh_from_db)()
        accounts = await sync_to_async(list)(BaseEthereumAccount.objects.all())
        tokens = await sync_to_async(list)(EthereumToken.ERC20tokens.all())

        for token in tokens:
            for account in accounts:
                event_filter = TokenEventFilterRegistry.get(w3=w3, token=token, account=account)
                token_mint_txs = event_filter.minter.get_new_entries()
                logger.debug(
                    f"Got {len(token_mint_txs)} {token.code} mint events for {account.address}"
                )
                for event in token_mint_txs:
                    await sync_to_async(process_erc223_token_mint_event)(
                        w3=w3, account=account, token=token, event=event
                    )

        await asyncio.sleep(BLOCK_CREATION_INTERVAL)


async def listen_pending_transfers(w3: Web3, **kw):
    await sync_to_async(wait_for_connection)(w3)
    tx_filter = w3.eth.filter("pending")
    chain_id = int(w3.net.version)

    while True:
        chain = await sync_to_async(Chain.make)(chain_id=chain_id)
        await asyncio.sleep(BLOCK_CREATION_INTERVAL / 2)
        await sync_to_async(process_pending_transfers)(w3, chain, tx_filter)


async def run_erc20_deposit_indexer(w3: Web3, **kw):
    await sync_to_async(wait_for_connection)(w3)
    chain_id = int(w3.net.version)
    chain = await sync_to_async(Chain.make)(chain_id=chain_id)

    accounts = await sync_to_async(list)(BaseEthereumAccount.objects.all())
    tokens = await sync_to_async(list)(EthereumToken.ERC20tokens.all())

    starting_block = 0
    while starting_block < chain.highest_block:
        for token in tokens:
            for account in accounts:
                end = min(starting_block + BLOCK_SCAN_RANGE, chain.highest_block)
                await sync_to_async(index_account_erc20_transfers)(
                    w3=w3,
                    account=account,
                    token=token,
                    starting_block=starting_block,
                    end_block=end,
                )
        starting_block += BLOCK_SCAN_RANGE


async def run_erc20_approval_indexer(w3: Web3, **kw):
    await sync_to_async(wait_for_connection)(w3)
    chain_id = int(w3.net.version)
    chain = await sync_to_async(Chain.make)(chain_id=chain_id)

    accounts = await sync_to_async(list)(BaseEthereumAccount.objects.all())
    tokens = await sync_to_async(list)(EthereumToken.ERC20tokens.all())

    starting_block = 0
    while starting_block < chain.highest_block:
        for token in tokens:
            for account in accounts:
                end = min(starting_block + BLOCK_SCAN_RANGE, chain.highest_block)
                await sync_to_async(index_account_erc20_approvals)(
                    w3=w3,
                    account=account,
                    token=token,
                    starting_block=starting_block,
                    end_block=end,
                )
        starting_block += BLOCK_SCAN_RANGE
