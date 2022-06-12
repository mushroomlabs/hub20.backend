from rest_framework import serializers

from hub20.apps.core.serializers import PaymentRouteSerializer, PaymentSerializer

from ..models import BlockchainPayment, BlockchainPaymentRoute
from .fields import AddressSerializerField, HexadecimalField


class BlockchainPaymentSerializer(PaymentSerializer):
    transaction = HexadecimalField(source="transaction.hash", read_only=True)
    block = serializers.IntegerField(source="transaction.block.number", read_only=True)

    class Meta:
        model = BlockchainPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "transaction", "block")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "transaction",
            "block",
        )


class BlockchainPaymentRouteSerializer(PaymentRouteSerializer):
    address = AddressSerializerField(source="account.address", read_only=True)
    expiration_block = serializers.IntegerField(source="expiration_block_number", read_only=True)

    class Meta:
        model = BlockchainPaymentRoute
        fields = PaymentRouteSerializer.Meta.fields + (
            "address",
            "expiration_block",
        )
        read_only_fields = PaymentRouteSerializer.Meta.read_only_fields + (
            "address",
            "expiration_block",
        )


__all__ = ["BlockchainPaymentSerializer", "BlockchainPaymentRouteSerializer"]
