from rest_framework import serializers

from hub20.apps.core.serializers import PaymentNetworkSerializer, PaymentNetworkStatusSerializer

from ..analytics import estimate_gas_price
from ..models import BlockchainPaymentNetwork


class BlockchainPaymentNetworkSerializer(PaymentNetworkSerializer):
    short_name = serializers.CharField(source="chain.short_name")
    chain_id = serializers.IntegerField(source="chain.id")
    token = serializers.HyperlinkedRelatedField(
        view_name="token-detail", source="chain.native_token", read_only=True
    )

    class Meta:
        model = BlockchainPaymentNetwork
        fields = read_only_fields = PaymentNetworkSerializer.Meta.fields + (
            "short_name",
            "chain_id",
            "token",
        )


class BlockchainStatusSerializer(PaymentNetworkStatusSerializer):
    height = serializers.IntegerField(source="chain.highest_block", read_only=True)
    online = serializers.BooleanField(source="chain.provider.connected")
    synced = serializers.BooleanField(source="chain.provider.synced")
    gas_price_estimate = serializers.SerializerMethodField()

    def get_gas_price_estimate(self, obj):
        return estimate_gas_price(obj.chain_id)

    class Meta:
        model = BlockchainPaymentNetwork
        fields = read_only_fields = (
            "url",
            "height",
            "online",
            "synced",
            "gas_price_estimate",
        )


__all__ = ["BlockchainPaymentNetworkSerializer", "BlockchainStatusSerializer"]
