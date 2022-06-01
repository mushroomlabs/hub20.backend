from django.db import models

from .accounts import BaseWallet
from .blockchain import Chain
from .tokens import Erc20Token


class AbstractChainIndexer(models.Model):
    chain = models.ForeignKey(
        Chain, related_name="%(app_label)s_%(class)s_indexers", on_delete=models.CASCADE
    )
    last_block = models.PositiveBigIntegerField(default=1)

    class Meta:
        abstract = True


class Erc20TokenTransferIndexer(AbstractChainIndexer):
    token = models.ForeignKey(
        Erc20Token, related_name="transfer_indexer", on_delete=models.CASCADE
    )
    account = models.ForeignKey(
        BaseWallet, related_name="erc20_transfer_indexer", on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.account.address} transfers of {self.token}"


class NativeTokenTransferIndexer(AbstractChainIndexer):
    account = models.ForeignKey(
        BaseWallet, related_name="native_token_transfer_indexer", on_delete=models.CASCADE
    )


__all__ = ["Erc20TokenTransferIndexer", "NativeTokenTransferIndexer"]
