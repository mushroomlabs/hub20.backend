from hub20.apps.core.serializers import BaseTransferSerializer

from ..models import BlockchainTransfer
from .fields import AddressSerializerField


class BlockchainWithdrawalSerializer(BaseTransferSerializer):
    address = AddressSerializerField()

    class Meta:
        model = BlockchainTransfer
        fields = BaseTransferSerializer.Meta.fields + ("address",)


__all__ = ["BlockchainWithdrawalSerializer"]
