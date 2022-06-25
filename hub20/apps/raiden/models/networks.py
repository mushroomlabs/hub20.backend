from __future__ import annotations

from django.db import models

from hub20.apps.core.models.networks import PaymentNetwork
from hub20.apps.core.models.tokens import Token_T
from hub20.apps.ethereum.models import Chain

from .raiden import TokenNetwork


class RaidenPaymentNetwork(PaymentNetwork):
    chain = models.OneToOneField(Chain, on_delete=models.CASCADE, db_column="base_chain_id")

    @property
    def provider(self):
        return self.chain.raiden_node.provider

    def supports_token(self, token: Token_T):
        return all(
            (
                token.is_listed,
                token.chain_id == self.chain_id,
                TokenNetwork.objects.filter(token_id=token.id).exists(),
            )
        )


__all__ = ["RaidenPaymentNetwork"]
