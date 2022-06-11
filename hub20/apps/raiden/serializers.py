from rest_framework import serializers

from hub20.apps.core.serializers import (
    PaymentNetworkSerializer,
    PaymentNetworkStatusSerializer,
    PaymentSerializer,
)

from . import models
from .client import RaidenClient


class RaidenPaymentNetworkSerializer(PaymentNetworkSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = models.RaidenPaymentNetworkSerializer
        fields = read_only_fields = PaymentNetworkSerializer.Meta.read_only_fields + ("chain",)


class RaidenStatusSerializer(PaymentNetworkStatusSerializer):
    hostname = serializers.CharField(source="chain.raiden_node.hostname")

    online = serializers.SerializerMethodField()

    def get_online(self, obj):
        client = RaidenClient(raiden_node=obj.chain.raiden_node)
        return "ready" == client.get_status()

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
