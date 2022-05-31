import logging

from django.db import models

from hub20.apps.core.models.networks import PaymentNetwork

from ..typing import Token_T
from .blockchain import Chain

logger = logging.getLogger(__name__)


class BlockchainPaymentNetwork(PaymentNetwork):
    chain = models.OneToOneField(Chain, on_delete=models.CASCADE)

    def supports_token(self, token: Token_T):
        return token.chain_id == self.chain_id and token.is_listed


class ChainMetadata(models.Model):
    chain = models.OneToOneField(Chain, related_name="info", on_delete=models.CASCADE)
    short_name = models.SlugField(null=True)
    testing_for = models.ForeignKey(
        Chain, null=True, blank=True, related_name="testnets", on_delete=models.CASCADE
    )
    rollup_for = models.ForeignKey(
        Chain, null=True, blank=True, related_name="rollups", on_delete=models.CASCADE
    )
    sidechain_for = models.ForeignKey(
        Chain, null=True, blank=True, related_name="sidechains", on_delete=models.CASCADE
    )


class Explorer(models.Model):
    chain = models.ForeignKey(Chain, related_name="explorers", on_delete=models.CASCADE)
    name = models.CharField(max_length=200, null=True)
    url = models.URLField()
    standard = models.CharField(max_length=200, null=True)

    class Meta:
        unique_together = ("url", "chain")


__all__ = ["ChainMetadata", "Explorer", "BlockchainPaymentNetwork"]
