from hub20.apps.core.serializers import BaseWithdrawalSerializer

from ..models import BlockchainTransfer
from .fields import AddressSerializerField


class BlockchainWithdrawalSerializer(BaseWithdrawalSerializer):
    address = AddressSerializerField()

    class Meta:
        model = BlockchainTransfer
        fields = BaseWithdrawalSerializer.Meta.fields + ("address",)


__all__ = ["BlockchainWithdrawalSerializer"]
