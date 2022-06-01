from __future__ import annotations

import logging
from asyncio.exceptions import TimeoutError
from typing import Optional
from urllib.parse import urlparse

from django.db import models
from django.db.transaction import atomic
from requests.exceptions import ConnectionError, HTTPError
from web3 import Web3
from web3._utils.events import get_event_data
from web3._utils.filters import construct_event_filter_params
from web3.exceptions import ExtraDataLengthError, LogTopicError, TransactionNotFound
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider

from hub20.apps.core.models.networks import PaymentNetworkProvider
from hub20.apps.core.tasks import broadcast_event

from .. import analytics
from ..abi.tokens import EIP20_ABI
from ..constants import Events
from .accounts import BaseWallet
from .blockchain import Transaction, TransactionDataRecord, TransferEvent
from .fields import Web3ProviderURLField
from .indexers import Erc20TokenTransferIndexer
from .tokens import Erc20Token

logger = logging.getLogger(__name__)


def get_web3(provider_url: str) -> Web3:
    endpoint = urlparse(provider_url)

    provider_class = {
        "http": HTTPProvider,
        "https": HTTPProvider,
        "ws": WebsocketProvider,
        "wss": WebsocketProvider,
    }.get(endpoint.scheme, IPCProvider)

    w3 = Web3(provider_class(provider_url))
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

    @atomic()
    def activate(self):
        similar_providers = Web3Provider.objects.exclude(id=self.id).filter(
            network__blockchainpaymentnetwork__chain=self.chain
        )
        similar_providers.update(is_active=False)
        self.is_active = True
        self.save()

    def __str__(self):
        return self.hostname

    def update_configuration(self):
        try:
            w3 = get_web3(provider_url=self.url)
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

    def _make_web3(self) -> Web3:
        w3 = get_web3(provider_url=self.url)

        if self.requires_geth_poa_middleware:
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        price_strategy = (
            eip1559_price_strategy if self.supports_eip1559 else historical_trend_price_strategy
        )
        w3.eth.setGasPriceStrategy(price_strategy)

        return w3

    def _check_node_is_connected(self):
        is_online = self._is_node_connected()

        if self.connected and not is_online:
            logger.info(f"Node {self.hostname} went offline")
            self.connected = False
            self.save()
            broadcast_event(event=Events.PROVIDER_OFFLINE.value, chain_id=self.chain.id)

        elif is_online and not self.connected:
            logger.info(f"Node {self.hostname} is back online")
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
        chain = self.chain
        block_number = self.w3.eth.block_number
        if chain.highest_block > block_number:
            chain.blocks.filter(number__gt=block_number).delete()

            chain.highest_block = block_number
            chain.save()

    def index_token_transfers(self, token: Erc20Token, wallet: BaseWallet):
        if token.chain != self.chain:
            logger.warning(f"{token} is not on the same chain as {self}")
            return

        indexer, _ = Erc20TokenTransferIndexer.objects.get_or_create(
            chain=token.chain, account=wallet, token=token
        )

        contract = self.w3.eth.contract(abi=EIP20_ABI, address=token.address)
        abi = contract.events.Transfer._get_event_abi()

        current_block = self.w3.eth.block_number

        while indexer.last_block < current_block:
            from_block = indexer.last_block
            to_block = min(current_block, from_block + self.max_block_scan_range)

            logger.debug(f"Indexer {indexer} running between {from_block} and {to_block}")
            _, event_filter_params = construct_event_filter_params(
                abi, self.w3.codec, fromBlock=from_block, toBlock=to_block
            )

            try:
                for log in self.w3.eth.get_logs(event_filter_params):
                    try:
                        event_data = get_event_data(self.w3.codec, abi, log)
                        sender = event_data.args._from
                        recipient = event_data.args._to

                        if wallet.address in [sender, recipient]:
                            try:
                                tx_data = self.w3.eth.get_transaction(event_data.transactionHash)
                                tx_receipt = self.w3.eth.get_transaction_receipt(
                                    event_data.transactionHash
                                )
                                block_data = self.w3.eth.get_block(tx_receipt.blockHash)
                                amount = token.from_wei(event_data.args._value)

                                TransactionDataRecord.make(
                                    chain_id=token.chain_id, tx_data=tx_data
                                )
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

                            except TransactionNotFound:
                                logger.warning(
                                    f"Failed to get transaction {event_data.transactionHash.hex()}"
                                )
                    except LogTopicError:
                        pass
            except TimeoutError:
                logger.error(f"Timeout when getting transfer events from {self.hostname}")
                self.max_block_scan_range = int(self.max_block_scan_range * 0.9)
                self.save()
            except Exception as exc:
                logger.error(f"Error getting logs from {self.hostname}: {exc}")
            else:
                indexer.last_block = to_block
                indexer.save()

    def _is_node_connected(self):
        logger.debug(f"Checking connection for {self}")
        try:
            is_online = self.w3.isConnected()

            if self.chain.is_scaling_network:
                return is_online

            if is_online and self.supports_peer_count:
                return is_online and self.w3.net.peer_count > 0

        except ConnectionError:
            is_online = False
        except ValueError:
            # The node does not support the peer count method. Assume healthy.
            self.supports_peer_count = False
            self.save()
        except Exception as exc:
            logger.error(f"Could not check {self.hostname}: {exc}")
            is_online = False

        return is_online

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

    def sync(self):
        logger.info(f"Syncing {self}")
        self._check_node_is_connected()
        self._check_node_is_synced()

        if not (self.connected and self.synced):
            logger.debug(f"Can not sync with {self}")
            return

        self._check_chain_reorganization()

        for token in Erc20Token.tradeable.filter(chain=self.chain):
            for wallet in BaseWallet.objects.all():
                self.index_token_transfers(token=token, wallet=wallet)

    def check_open_payments(self):
        logger.info(f"checking open payments on {self}")
        self.update_configuration()

    def execute_transfers(self):
        logger.info(f"Executing transfers routed via {self}")
        self.update_configuration()


__all__ = ["Web3Provider"]
