from __future__ import annotations

import logging
import time
from typing import Optional, Tuple, Union
from urllib.parse import urlparse

import celery_pubsub
from django.db import models
from django.db.transaction import atomic
from django.db.utils import IntegrityError
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params
from web3.datastructures import AttributeDict
from web3.exceptions import BlockNotFound, ExtraDataLengthError, LogTopicError, TransactionNotFound
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider
from web3.types import TxReceipt

from hub20.apps.core.models.providers import PaymentNetworkProvider
from hub20.apps.core.models.tokens import Token_T, TokenAmount
from hub20.apps.core.tasks import broadcast_event
from hub20.apps.ethereum.exceptions import Web3TransactionError

from .. import analytics
from ..abi.tokens import EIP20_ABI, ERC223_ABI
from ..constants import SENTINEL_ADDRESS
from ..typing import Address
from .accounts import BaseWallet, EthereumAccount_T
from .blockchain import (
    Block,
    Transaction,
    TransactionDataRecord,
    TransferEvent,
    serialize_web3_data,
)
from .fields import Web3ProviderURLField
from .tokens import Erc20Token, EthereumToken_T

GAS_REQUIRED_FOR_MINT: int = 100_000
GAS_TRANSFER_LIMIT: int = 200_000

logger = logging.getLogger(__name__)


def get_web3(provider_url: str, timeout: int) -> Web3:
    endpoint = urlparse(provider_url)

    provider_class = {
        "http": HTTPProvider,
        "https": HTTPProvider,
        "ws": WebsocketProvider,
        "wss": WebsocketProvider,
    }.get(endpoint.scheme, IPCProvider)

    http_request_params = dict(request_kwargs={"timeout": timeout})
    ws_connection_params = dict(websocket_timeout=timeout)

    params = {
        "http": http_request_params,
        "https": http_request_params,
        "ws": ws_connection_params,
        "wss": ws_connection_params,
    }.get(endpoint.scheme, {})

    w3 = Web3(provider_class(provider_url, **params))
    return w3


def eip1559_price_strategy(w3: Web3, *args, **kw):
    try:
        current_block = w3.eth.get_block("latest")
        return analytics.recommended_eip1559_gas_price(
            current_block, max_priority_fee=w3.eth.max_priority_fee
        )
    except Exception as exc:
        chain_id = w3.eth.chain_id
        logger.exception(f"Error when getting price estimate for {chain_id}", exc_info=exc)
        return analytics.estimate_gas_price(chain_id)


def historical_trend_price_strategy(w3: Web3, *args, **kw):
    return analytics.estimate_gas_price(w3.eth.chain_id)


class Web3Provider(PaymentNetworkProvider):
    DEFAULT_BLOCK_CREATION_INTERVAL = 10
    DEFAULT_MAX_BLOCK_SCAN_RANGE = 5000
    DEFAULT_REQUEST_TIMEOUT = 15

    url = Web3ProviderURLField()
    client_version = models.CharField(max_length=300, null=True)
    requires_geth_poa_middleware = models.BooleanField(default=False)
    supports_pending_filters = models.BooleanField(default=False)
    supports_eip1559 = models.BooleanField(default=False)
    supports_peer_count = models.BooleanField(default=True)
    block_creation_interval = models.PositiveIntegerField(default=DEFAULT_BLOCK_CREATION_INTERVAL)
    max_block_scan_range = models.PositiveIntegerField(default=DEFAULT_MAX_BLOCK_SCAN_RANGE)

    @property
    def sync_interval(self):
        return 2 * self.block_creation_interval

    @property
    def hostname(self):
        return urlparse(self.url).hostname

    @property
    def chain(self):
        return self.network.blockchainpaymentnetwork.chain

    @property
    def w3(self):
        if not getattr(self, "_w3", None):
            self._w3 = self._make_web3()
        return self._w3

    def __str__(self):
        return self.hostname

    def _make_web3(self) -> Web3:
        w3 = get_web3(provider_url=self.url, timeout=self.DEFAULT_REQUEST_TIMEOUT)

        if self.requires_geth_poa_middleware:
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        price_strategy = (
            eip1559_price_strategy if self.supports_eip1559 else historical_trend_price_strategy
        )
        w3.eth.set_gas_price_strategy(price_strategy)

        return w3

    def _is_node_connected(self):
        logger.debug(f"Checking connection for {self}")
        try:
            is_connected = self.w3.isConnected()

            if self.chain.is_scaling_network:
                return is_connected

            if is_connected and self.supports_peer_count:
                return is_connected and self.w3.net.peer_count > 0

        except ConnectionError:
            is_connected = False
        except ValueError:
            # The node does not support the peer count method. Assume healthy.
            self.supports_peer_count = False
            self.save()
        except Exception as exc:
            logger.error(f"Could not check {self.hostname}: {exc}")
            is_connected = False

        return is_connected

    def _is_node_synced(self):
        if self.chain.is_scaling_network:
            return True
        try:
            is_synced = bool(not self.w3.eth.syncing)
        except (ValueError, AttributeError):
            # The node does not support the eth_syncing method. Assume healthy.
            is_synced = True
        except (ConnectionError, HTTPError) as exc:
            logger.error(f"Failed to connect to {self.hostname}: {exc}")
            is_synced = False

        return is_synced

    def _check_node_is_connected(self):
        is_connected = self._is_node_connected()

        if self.connected and not is_connected:
            logger.info(f"Node {self.hostname} is disconnected")
            self.connected = False
            self.save()
            broadcast_event(
                event=self.network.EVENT_MESSAGES.PROVIDER_OFFLINE.value,
                network_id=self.network.id,
            )

        elif is_connected and not self.connected:
            logger.info(f"Node {self.hostname} is reconnected")
            self.connected = True
            self.save()
            broadcast_event(
                event=self.network.EVENT_MESSAGES.PROVIDER_ONLINE.value, network=self.network.id
            )

    def _check_node_is_synced(self):
        is_synced = self._is_node_synced()

        if self.synced and not is_synced:
            logger.info(f"Node {self.hostname} is out of sync")
            self.synced = False
            self.save()
            broadcast_event(
                event=self.network.EVENT_MESSAGES.PROVIDER_OFFLINE.value, network=self.network.id
            )

        elif is_synced and not self.synced:
            logger.info(f"Node {self.hostname} is back in sync")
            self.synced = True
            self.save()
            broadcast_event(
                event=self.network.EVENT_MESSAGES.PROVIDER_ONLINE.value, network=self.network.id
            )

    @atomic
    def _check_chain_reorganization(self):
        if self.is_online:
            block_number = self.w3.eth.block_number
            if self.chain.highest_block > block_number:
                self.chain.blocks.filter(number__gt=block_number).delete()
                self.chain.highest_block = block_number
                self.chain.save()

    def _extract_transfer_event_from_erc20_token_transfer(self, wallet, event_data):
        sender = event_data.args._from
        recipient = event_data.args._to
        token_address = event_data.address
        if wallet.address in [sender, recipient]:
            try:
                token = self.chain.tokens.filter(address=token_address).first() or self.save_token(
                    token_address
                )

                tx_data = self.w3.eth.get_transaction(event_data.transactionHash)
                tx_receipt = self.w3.eth.get_transaction_receipt(event_data.transactionHash)
                block_data = self.w3.eth.get_block(tx_receipt.blockHash)
                amount = token.from_wei(event_data.args._value)
            except TransactionNotFound:
                logger.warning(f"Failed to get transaction {event_data.transactionHash.hex()}")
                return

            try:
                TransactionDataRecord.make(chain_id=token.chain_id, tx_data=tx_data)
                tx = Transaction.make(
                    chain_id=token.chain_id,
                    block_data=block_data,
                    tx_receipt=tx_receipt,
                )
                wallet.transactions.add(tx)
                TransferEvent.objects.create(
                    transaction=tx,
                    sender=sender,
                    recipient=recipient,
                    amount=amount.amount,
                    currency=amount.currency,
                    log_index=event_data.logIndex,
                )
            except IntegrityError:
                logger.exception(f"Failed to save tx {event_data.transactionHash} from {self}")

            except Exception:
                logger.exception("Failed to create transaction or transfer event")

    def _get_erc20_transfer_events(self, start_block, end_block):
        contract = self.w3.eth.contract(abi=EIP20_ABI)
        abi = contract.events.Transfer._get_event_abi()

        _, event_filter_params = construct_event_filter_params(
            abi, self.w3.codec, fromBlock=start_block, toBlock=end_block
        )

        for log in self.w3.eth.get_logs(event_filter_params):
            try:
                yield get_event_data(self.w3.codec, abi, log)
            except LogTopicError:
                pass
            except Exception as exc:
                logger.error(f"Error processing log from {self.hostname}: {exc}")

    @atomic()
    def activate(self):
        similar_providers = Web3Provider.objects.exclude(id=self.id).filter(
            network__blockchainpaymentnetwork__chain=self.chain
        )
        similar_providers.update(is_active=False)
        self.is_active = True
        self.save()

    def run_checks(self):
        self._check_node_is_connected()
        self._check_node_is_synced()
        self._check_chain_reorganization()

    def update_stats(self, block_data):
        chain_id = self.chain.id
        if self.supports_eip1559:
            try:
                analytics.MAX_PRIORITY_FEE_TRACKER.set(chain_id, self.w3.eth.max_priority_fee)
            except Exception:
                logger.exception(f"Failed to get max priority fee from {self}")
        try:
            block_history = analytics.get_historical_block_data(chain_id)
            block_history.push(block_data)
        except Exception:
            logger.exception(f"Failed to record historical data about {self.chain.name}")

    def update_configuration(self):
        try:
            w3 = get_web3(provider_url=self.url, timeout=self.DEFAULT_REQUEST_TIMEOUT)
            try:
                version: Optional[str] = w3.clientVersion
            except ValueError:
                version = None

            try:
                max_fee = w3.eth.max_priority_fee
                eip1559 = bool(type(max_fee) is int)
            except ValueError:
                eip1559 = False
            except HTTPError as exc:
                if not self.chain.is_scaling_network:
                    raise exc
                else:
                    eip1559 = False

            try:
                w3.eth.filter("pending")
                pending_filters = True
            except ValueError:
                pending_filters = False
            except HTTPError as exc:
                if not self.chain.is_scaling_network:
                    raise exc
                else:
                    pending_filters = False

            try:
                supports_peer_count = type(w3.net.peer_count) is int
            except ValueError:
                supports_peer_count = False
            except HTTPError as exc:
                if not self.chain.is_scaling_network:
                    raise exc
                else:
                    supports_peer_count = False

            try:
                w3.eth.get_block("latest")
                requires_geth_poa_middleware = False
            except ExtraDataLengthError:
                requires_geth_poa_middleware = True

            self.client_version = version
            self.supports_eip1559 = eip1559
            self.supports_pending_filters = pending_filters
            self.requires_geth_poa_middleware = requires_geth_poa_middleware
            self.supports_peer_count = supports_peer_count

            self.save()
        except Exception as exc:
            logger.exception(f"Failed to update configuration for {self}: {exc}")

    def mint_tokens(self, account: EthereumAccount_T, amount: TokenAmount):
        logger.debug(f"Minting {amount.formatted}")
        token_proxy = self.w3.eth.contract(
            address=Web3.toChecksumAddress(amount.currency.address),
            abi=ERC223_ABI,
        )

        self.send_transaction(
            contract_function=token_proxy.functions.mint,
            account=account,
            contract_args=(amount.as_wei,),
            gas=GAS_REQUIRED_FOR_MINT,
        )

    def save_token(self, token_address) -> Erc20Token:
        address = Web3.toChecksumAddress(token_address)
        contract = self.w3.eth.contract(abi=EIP20_ABI, address=address)
        token_data = {
            "name": contract.functions.name().call(),
            "symbol": contract.functions.symbol().call(),
            "decimals": contract.functions.decimals().call(),
        }

        token, _ = Erc20Token.objects.update_or_create(
            chain=self.chain, address=address, defaults=token_data
        )
        return token

    def get_erc20_token_transfer_filter(self, token, start_block, end_block):
        contract = self.w3.eth.contract(
            abi=EIP20_ABI, address=Web3.toChecksumAddress(token.address)
        )
        return contract.events.Transfer.createFilter(
            fromBlock=start_block, toBlock=end_block, address=token.address
        )

    def encode_transfer_call(self, recipient_address, amount: TokenAmount):
        contract = self.w3.eth.contract(address=amount.currency.subclassed.address, abi=EIP20_ABI)

        return contract.encodeABI("transfer", [recipient_address, amount.as_wei])

    def extract_native_token_transfers(self, block_data):
        transactions = block_data["transactions"]
        txs = [t for t in transactions if t.value > 0]

        if not txs:
            return

        token = self.chain.native_token

        for transaction_data in txs:
            sender = transaction_data["from"]
            recipient = transaction_data["to"]

            amount = token.from_wei(transaction_data.value)

            tx_receipt = self.w3.eth.get_transaction_receipt(transaction_data.hash)
            tx = Transaction.make(
                chain_id=token.chain_id,
                block_data=block_data,
                tx_receipt=tx_receipt,
            )

            for wallet in BaseWallet.objects.filter(address__in=[sender, recipient]):
                wallet.transactions.add(tx)

            try:
                TransferEvent.objects.get_or_create(
                    transaction=tx,
                    sender=sender,
                    recipient=recipient,
                    amount=amount.amount,
                    currency=amount.currency,
                )
            except Exception:
                logger.exception("Failed to create transfer event")

    def extract_erc20_transfer_events_from_wallet(self, wallet, start_block, end_block):
        for event_data in self._get_erc20_transfer_events(start_block, end_block):
            self._extract_transfer_event_from_erc20_token_transfer(wallet, event_data)

    def extract_erc20_token_transfer_events(self, start_block, end_block):
        wallets = list(BaseWallet.objects.all())

        for event_data in self._get_erc20_transfer_events(start_block, end_block):
            for wallet in wallets:
                self._extract_transfer_event_from_erc20_token_transfer(wallet, event_data)

    def get_erc20_token_transfer_gas_estimate(self, token: Erc20Token):
        contract = self.w3.eth.contract(abi=EIP20_ABI, address=token.address)
        return contract.functions.transfer(SENTINEL_ADDRESS, 0).estimate_gas(
            {"from": SENTINEL_ADDRESS}
        )

    def get_transfer_fee_estimate(self, token: Token_T) -> TokenAmount:
        native_token = token.chain.native_token

        gas_price = self.w3.eth.generate_gas_price()
        gas_estimate = (
            self.get_erc20_token_transfer_gas_estimate(token=token) if token.is_ERC20 else 21000
        )
        return native_token.from_wei(gas_estimate * gas_price)

    def send_transaction(
        self,
        contract_function,
        account: EthereumAccount_T,
        gas,
        contract_args: Optional[Tuple] = None,
        **kw,
    ) -> TxReceipt:
        nonce = kw.pop("nonce", self.w3.eth.getTransactionCount(account.address))

        transaction_params = {
            "chainId": int(self.w3.net.version),
            "nonce": nonce,
            "gasPrice": kw.pop("gas_price", self.w3.eth.generate_gas_price()),
            "gas": gas,
        }

        transaction_params.update(**kw)

        try:
            result = contract_function(*contract_args) if contract_args else contract_function()
            transaction_data = result.buildTransaction(transaction_params)
            signed = self.w3.eth.account.signTransaction(transaction_data, account.private_key)
            tx_hash = self.w3.eth.sendRawTransaction(signed.rawTransaction)
            return self.w3.eth.waitForTransactionReceipt(tx_hash)
        except ValueError as exc:
            try:
                if exc.args[0].get("message") == "nonce too low":
                    logger.warning("Node reported that nonce is too low. Trying tx again...")
                    kw["nonce"] = nonce + 1
                    return self.send_transaction(
                        contract_function,
                        account,
                        gas,
                        contract_args=contract_args,
                        **kw,
                    )
            except (AttributeError, IndexError):
                pass

            raise Web3TransactionError from exc

    @atomic()
    def update_account_balance(self, account: EthereumAccount_T, token: EthereumToken_T):
        current_block = self.w3.eth.block_number
        block_data = self.w3.eth.get_block(current_block)
        if token.is_ERC20:
            contract = self.w3.eth.contract(abi=EIP20_ABI, address=token.address)
            current_balance = contract.functions.balanceOf(account.address).call()
            balance = token.from_wei(current_balance)
        else:
            balance = token.from_wei(
                self.w3.eth.get_balance(account.address, block_identifier=block_data.hash.hex())
            )
        block = Block.make(block_data=block_data, chain_id=self.chain.id)

        account.balance_records.create(
            currency=balance.currency, amount=balance.amount, block=block
        )

    def select_for_transfer(self, amount: TokenAmount) -> Union[EthereumAccount_T, None]:
        native_token = self.chain.native_token
        transferred_token = amount.currency.subclassed

        assert (
            transferred_token.chain == native_token.chain
        ), "{transferred_token} and {native_token} are not on the same chain"

        transfer_fee: TokenAmount = self.get_transfer_fee_estimate(token=transferred_token)

        is_native_token_transfer = amount.currency.subclassed == native_token

        if is_native_token_transfer:
            amount += transfer_fee

        for account in BaseWallet.objects.select_subclasses().order_by("?"):
            self.update_account_balance(account=account, token=native_token)
            if not is_native_token_transfer:
                self.update_account_balance(account=account, token=transferred_token)

            token_balance = account.current_balance(transferred_token)
            native_token_balance = account.current_balance(native_token)

            has_token_balance = token_balance and token_balance >= amount
            has_fee_funds = native_token_balance and native_token_balance >= transfer_fee

            if has_token_balance and has_fee_funds:
                return account

        else:
            return None

    def transfer(
        self, account: EthereumAccount_T, amount: TokenAmount, address: Address, *args, **kw
    ) -> TransactionDataRecord:
        token: EthereumToken_T = amount.currency.subclassed

        chain_id = self.chain.id

        message = f"Connected to network {chain_id}, token {token.symbol} is on {token.chain_id}"
        assert token.chain_id == chain_id, message

        transaction_params = {
            "chainId": chain_id,
            "nonce": self.w3.eth.getTransactionCount(account.address),
            "gasPrice": self.w3.eth.generate_gas_price(),
            "gas": GAS_TRANSFER_LIMIT,
            "from": account.address,
        }

        if token.is_ERC20:
            transaction_params.update(
                {
                    "to": token.address,
                    "value": 0,
                    "data": self.encode_transfer_call(address, amount),
                }
            )
        else:
            transaction_params.update({"to": address, "value": amount.as_wei})
        return transaction_params

        signed_tx = self.sign_transaction(transaction_data=transaction_params)
        chain_id = self.chain.id
        tx_hash = self.w3.eth.sendRawTransaction(signed_tx.rawTransaction)
        try:
            tx_data = self.w3.eth.get_transaction(tx_hash)
            return TransactionDataRecord.make(chain_id=chain_id, tx_data=tx_data, force=True)
        except TransactionNotFound:
            return TransactionDataRecord.make(
                chain_id=chain_id, tx_data=AttributeDict(transaction_params)
            )

    def sign_transaction(self, account: EthereumAccount_T, transaction_data, *args, **kw):
        if not hasattr(account, "private_key"):
            raise NotImplementedError(f"{account} can not sign transactions")
        return self.w3.eth.account.signTransaction(transaction_data, account.private_key)

    def run(self):
        MIN_TIMEOUT = 2
        MAX_TIMEOUT = 60
        self.update_configuration()

        timeout = MIN_TIMEOUT

        while True:
            self.run_checks()

            if self.is_online:
                timeout = MIN_TIMEOUT
            else:
                logger.warning(f"{self} is not online. Sleeping {timeout} seconds...")
                time.sleep(timeout)
                timeout = min(MAX_TIMEOUT, 2 * timeout)
                continue

            current_block = self.w3.eth.block_number
            if current_block > self.chain.highest_block:
                try:
                    logger.debug(f"Getting block {current_block} from {self.hostname}")
                    block_data = self.w3.eth.get_block(current_block, full_transactions=True)
                    self.update_stats(block_data)
                except BlockNotFound:
                    logger.warning(f"Failed to get block {current_block} from {self}")
                else:
                    celery_pubsub.publish(
                        "blockchain.mined.block",
                        chain_id=self.w3.eth.chain_id,
                        block_data=serialize_web3_data(block_data),
                        provider_url=self.url,
                    )
                    self.chain.highest_block = current_block
                    self.chain.save()
            time.sleep(1)


__all__ = ["Web3Provider"]
