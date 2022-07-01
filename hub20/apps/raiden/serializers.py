from rest_framework import serializers

from hub20.apps.core.serializers import (
    BaseTransferSerializer,
    PaymentNetworkSerializer,
    PaymentNetworkStatusSerializer,
    PaymentSerializer,
)
from hub20.apps.ethereum.serializers.fields import AddressSerializerField

from . import models


class RaidenPaymentNetworkSerializer(PaymentNetworkSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = models.RaidenPaymentNetwork
        fields = read_only_fields = PaymentNetworkSerializer.Meta.read_only_fields + ("chain_id",)


class RaidenStatusSerializer(PaymentNetworkStatusSerializer):
    hostname = serializers.CharField(source="chain.raiden_node.hostname")
    online = serializers.BooleanField(source="provider.is_online")

    class Meta:
        model = models.RaidenPaymentNetwork
        fields = read_only_fields = PaymentNetworkStatusSerializer.Meta.fields + (
            "hostname",
            "online",
        )


class RaidenPaymentSerializer(PaymentSerializer):
    raiden = serializers.CharField(source="payment.channel.raiden.address")

    class Meta:
        model = models.RaidenPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "raiden")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "raiden",
        )


class RaidenTransferSerializer(BaseTransferSerializer):
    address = AddressSerializerField()

    class Meta:
        model = models.RaidenTransfer
        fields = BaseTransferSerializer.Meta.fields + ("address",)


__all__ = [
    "RaidenPaymentNetworkSerializer",
    "RaidenStatusSerializer",
    "RaidenPaymentSerializer",
    "RaidenTransferSerializer",
]
