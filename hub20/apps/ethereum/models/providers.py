from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import celery_pubsub
from django.db import models
from django.db.transaction import atomic
from web3 import Web3
from web3.exceptions import ExtraDataLengthError
from web3.middleware import geth_poa_middleware
from web3.providers import HTTPProvider, IPCProvider, WebsocketProvider

from hub20.apps.core.models.networks import PaymentNetworkProvider

from .. import analytics
from .fields import Web3ProviderURLField

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
    def hostname(self):
        return urlparse(self.url).hostname

    @property
    def w3(self):
        if not getattr(self, "_w3", None):
            self._w3 = self._make_web3()
        return self._w3

    @atomic()
    def activate(self):
        similar_providers = Web3Provider.objects.exclude(id=self.id).filter(
            network__blockchainpaymentnetwork__chain=self.network.blockchainpaymentnetwork.chain
        )
        similar_providers.update(is_active=False)
        self.is_active = True
        self.save()

    def __str__(self):
        return self.hostname

    def update_configuration(self):
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

        try:
            w3.eth.filter("pending")
            pending_filters = True
        except ValueError:
            pending_filters = False

        try:
            supports_peer_count = type(w3.net.peer_count) is int
        except ValueError:
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

    def _make_web3(self) -> Web3:
        w3 = get_web3(provider_url=self.url)

        if self.requires_geth_poa_middleware:
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        price_strategy = (
            eip1559_price_strategy if self.supports_eip1559 else historical_trend_price_strategy
        )
        w3.eth.setGasPriceStrategy(price_strategy)

        return w3

    def _check_connection(self):
        try:
            is_connected = self.w3.isConnected()
            is_online = is_connected and (
                self.network.chain.is_scaling_network or self.w3.net.peer_count > 0
            )
        except ConnectionError:
            is_online = False
        except ValueError:
            # The node does not support the peer count method. Assume healthy.
            is_online = is_connected
        except Exception as exc:
            logger.error(f"Could not check {self.hostname}: {exc}")
            is_online = False

        if self.connected and not is_online:
            logger.info(f"Node {self.hostname} went offline")
            celery_pubsub.publish(
                "node.connection.nok", chain_id=self.chain_id, provider_url=self.url
            )

        elif is_online and not self.connected:
            logger.info(f"Node {self.hostname} is back online")
            celery_pubsub.publish(
                "node.connection.ok", chain_id=self.chain_id, provider_url=self.url
            )

    def run(self):
        logger.info(f"Running {self}")


__all__ = ["Web3Provider"]
