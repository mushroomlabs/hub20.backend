from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse

import celery_pubsub
from django.db import models
from django.db.transaction import atomic
from django.db.utils import IntegrityError
from eth_utils import to_checksum_address
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params
from web3.exceptions import BlockNotFound, ExtraDataLengthError, LogTopicError, TransactionNotFound
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider

from hub20.apps.core.models.providers import PaymentNetworkProvider
from hub20.apps.core.tasks import broadcast_event

from .. import analytics
from ..abi.tokens import EIP20_ABI
from ..constants import Events
from .accounts import BaseWallet
from .blockchain import Transaction, TransactionDataRecord, TransferEvent, serialize_web3_data
from .fields import Web3ProviderURLField
from .tokens import Erc20Token

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
        w3.eth.setGasPriceStrategy(price_strategy)

        return w3

    def _check_node_is_connected(self):
        is_connected = self._is_node_connected()

        if self.connected and not is_connected:
            logger.info(f"Node {self.hostname} is disconnected")
            self.connected = False
            self.save()
            broadcast_event(event=Events.PROVIDER_OFFLINE.value, chain_id=self.chain.id)

        elif is_connected and not self.connected:
            logger.info(f"Node {self.hostname} is reconnected")
            self.connected = True
            self.save()
            broadcast_event(event=Events.PROVIDER_ONLINE.value, chain_id=self.chain.id)

    def _check_node_is_synced(self):
        is_synced = self._is_node_synced()

        if self.synced and not is_synced:
            logger.info(f"Node {self.hostname} is out of sync")
            self.synced = False
            self.save()
            broadcast_event(event=Events.PROVIDER_OFFLINE.value, chain_id=self.chain.id)

        elif is_synced and not self.synced:
            logger.info(f"Node {self.hostname} is back in sync")
            self.synced = True
            self.save()
            broadcast_event(event=Events.PROVIDER_ONLINE.value, chain_id=self.chain.id)

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

    def save_token(self, token_address):
        contract = self.w3.eth.contract(abi=EIP20_ABI, address=to_checksum_address(token_address))
        token_data = {
            "name": contract.functions.name().call(),
            "symbol": contract.functions.symbol().call(),
            "decimals": contract.functions.decimals().call(),
        }

        token, _ = Erc20Token.objects.update_or_create(
            chain=self.chain, address=token_address, defaults=token_data
        )
        return token

    def get_erc20_token_transfer_filter(self, token, start_block, end_block):
        contract = self.w3.eth.contract(abi=EIP20_ABI, address=to_checksum_address(token.address))
        return contract.events.Transfer.createFilter(
            dict(fromBlock=start_block, toBlock=end_block, address=token.address)
        )

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
