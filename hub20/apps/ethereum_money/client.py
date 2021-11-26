import logging
from functools import wraps
from typing import Optional

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from eth_utils import to_checksum_address
from ethereum.abi import ContractTranslator
from web3 import Web3
from web3.exceptions import MismatchedABI
from web3._utils.events import get_event_data

from hub20.apps.blockchain.client import (
    blockchain_scanner,
    get_transaction_by_hash,
    get_web3,
    log_web3_client_exception,
    wait_for_connection,
)
from hub20.apps.blockchain.models import BaseEthereumAccount, Chain, Transaction
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
from .typing import EthereumClient_T

logger = logging.getLogger(__name__)
EthereumAccount = get_ethereum_account_model()
User = get_user_model()


def erc20_owner_filter_args(account):
    return dict(fromBlock="latest", argument_filters={"_owner": account.address})


def erc20_incoming_filter_args(account):
    return dict(fromBlock="latest", argument_filters={"_to": account.address})


def erc20_outgoing_filter_args(account):
    return dict(fromBlock="latest", argument_filters={"_from": account.address})


def erc20_pending_incoming_args(account):
    return dict(fromBlock="latest", toBlock="pending", argument_filters={"_to": account.address})


def erc20_pending_outgoing_args(account):
    return dict(fromBlock="latest", toBlock="pending", argument_filters={"_from": account.address})


def get_transaction_events(transaction_receipt, event_abi):
    w3 = Web3()
    events = []
    for log in transaction_receipt.logs:
        try:
            event = get_event_data(w3.codec, event_abi, log)
            events.append(event)
        except MismatchedABI:
            pass
    return events


def blockchain_token_event_handler(abi, event, account_filter_args):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(*args, **kw):
            FILTER_REGISTRY = {}

            def get_filter(contract, event, token, account, **filter_params):
                key = (token.address, account.address)
                try:
                    return FILTER_REGISTRY[key]
                except KeyError:
                    event_type = getattr(contract.events, event)
                    new_filter = event_type.createFilter(**filter_params)
                    FILTER_REGISTRY[key] = new_filter
                    return new_filter

            w3: Web3 = get_web3()
            wait_for_connection(w3=w3)

            while True:
                try:
                    wait_for_connection(w3=w3)
                    tokens = await sync_to_async(list)(EthereumToken.ERC20tokens.all())
                    accounts = await sync_to_async(list)(BaseEthereumAccount.objects.all())

                    for token in tokens:
                        contract = w3.eth.contract(abi=abi, address=token.address)
                        for account in accounts:
                            filter_params = account_filter_args(account)
                            try:
                                event_filter = await sync_to_async(get_filter)(
                                    contract, event, token, account, **filter_params
                                )
                            except ValueError as exc:
                                logger.warning(f"Can not get {event} filter with {filter_params}")
                                log_web3_client_exception(exc)
                                return
                            entries = await sync_to_async(event_filter.get_new_entries)()
                            for event_entry in entries:
                                await sync_to_async(handler)(
                                    w3=w3, token=token, account=account, event=event_entry
                                )
                except Exception as exc:
                    logger.exception(f"Error on {handler.__name__}: {exc}")

        return wrapper

    return decorator


def token_scanner(handler):
    @wraps(handler)
    def wrapper(*args, **kw):
        return handler(tokens=EthereumToken.ERC20tokens.all(), *args, **kw)

    return wrapper


def account_scanner(handler):
    @wraps(handler)
    def wrapper(*args, **kw):
        return handler(accounts=BaseEthereumAccount.objects.all(), *args, **kw)

    return wrapper


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


def process_erc20_approval_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    logger.info(
        "{} is a tx with a {} approval event from {}".format(
            event.transactionHash.hex(), token.code, account.address
        )
    )
    transaction = get_transaction_by_hash(w3=w3, transaction_hash=event.transactionHash)
    if transaction:
        account.transactions.add(transaction)


def process_pending_incoming_erc20_transfer_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    logger.info(
        "Pending {} transfer to {}: {}".format(
            token.code, account.address, event.transactionHash.hex()
        )
    )
    incoming_transfer_broadcast.send(
        sender=EthereumToken,
        account=account,
        amount=token.from_wei(event.args._value),
        transaction_hash=event.transactionHash.hex(),
    )

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


def process_pending_outgoing_erc20_transfer_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    logger.info(
        "Pending {} transfer from {}: {}".format(
            token.code, account.address, event.transactionHash.hex()
        )
    )
    outgoing_transfer_broadcast.send(
        sender=EthereumToken,
        account=account,
        amount=token.from_wei(event.args._value),
        transaction_hash=event.transactionHash.hex(),
    )


def process_erc223_token_mint_event(
    w3: Web3, token: EthereumToken, account: EthereumAccount_T, event
):
    logger.info(
        "{} is a tx with a {} mint event for {}".format(
            event.transactionHash.hex(), token.code, account.address
        )
    )
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
    def select_for_transfer(
        cls,
        amount: EthereumTokenAmount,
        receiver: Optional[User] = None,
        address: Optional[Address] = None,
    ) -> Optional[EthereumClient_T]:
        w3 = get_web3()

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
                return cls(account=account, w3=w3)
        return None

    @classmethod
    def estimate_transfer_fees(cls, *args, **kw) -> EthereumTokenAmount:
        w3 = kw.pop("w3", get_web3())
        return get_max_fee(w3=w3)


@blockchain_token_event_handler(
    abi=EIP20_ABI, event="Transfer", account_filter_args=erc20_pending_incoming_args
)
def listen_pending_incoming_erc20_transfers(
    w3: Web3, token: EthereumToken, account: BaseEthereumAccount, event
):
    process_pending_incoming_erc20_transfer_event(w3=w3, token=token, account=account, event=event)


@blockchain_token_event_handler(
    abi=EIP20_ABI, event="Transfer", account_filter_args=erc20_pending_outgoing_args
)
def listen_pending_outgoing_erc20_transfers(
    w3: Web3, token: EthereumToken, account: BaseEthereumAccount, event
):
    process_pending_outgoing_erc20_transfer_event(w3=w3, token=token, account=account, event=event)


@blockchain_token_event_handler(
    abi=EIP20_ABI, event="Approval", account_filter_args=erc20_owner_filter_args
)
def listen_erc20_approvals(w3: Web3, token: EthereumToken, account: BaseEthereumAccount, event):
    logger.info(
        "{} is a tx with a {} approval event from {}".format(
            event.transactionHash.hex(), token.code, account.address
        )
    )
    transaction = get_transaction_by_hash(w3=w3, transaction_hash=event.transactionHash)
    if transaction:
        account.transactions.add(transaction)


@blockchain_scanner
@token_scanner
@account_scanner
def run_erc20_deposit_indexer(w3: Web3, starting_block: int, end_block: int, tokens, accounts):
    for token in tokens:
        for account in accounts:
            index_account_erc20_transfers(
                w3=w3,
                account=account,
                token=token,
                starting_block=starting_block,
                end_block=end_block,
            )


@blockchain_scanner
@token_scanner
@account_scanner
def run_erc20_approval_indexer(w3: Web3, starting_block: int, end_block: int, tokens, accounts):
    for token in tokens:
        for account in accounts:
            index_account_erc20_approvals(
                w3=w3,
                account=account,
                token=token,
                starting_block=starting_block,
                end_block=end_block,
            )
