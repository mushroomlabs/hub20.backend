import logging
from urllib.parse import urlparse

from django.db import models
from django.db.transaction import atomic

from hub20.apps.core.models.networks import PaymentNetworkProvider
from hub20.apps.core.settings import app_settings

from ..fields import Web3ProviderURLField

logger = logging.getLogger(__name__)


class Web3Provider(PaymentNetworkProvider):
    url = Web3ProviderURLField()
    client_version = models.CharField(max_length=300, null=True)
    requires_geth_poa_middleware = models.BooleanField(default=False)
    supports_pending_filters = models.BooleanField(default=False)
    supports_eip1559 = models.BooleanField(default=False)
    max_block_scan_range = models.PositiveIntegerField(default=app_settings.Blockchain.scan_range)

    @property
    def hostname(self):
        return urlparse(self.url).hostname

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


__all__ = ["Web3Provider"]
