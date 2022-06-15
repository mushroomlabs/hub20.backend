from rest_framework import serializers

from hub20.apps.core.serializers import TokenSerializer

from ..models import Chain, Erc20Token, NativeToken
from .fields import AddressSerializerField


class NativeTokenSerializer(TokenSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(queryset=Chain.active.distinct())

    class Meta:
        model = NativeToken
        fields = read_only_fields = TokenSerializer.Meta.read_only_fields + ("chain_id",)


class Erc20TokenSerializer(TokenSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(queryset=Chain.active.distinct())
    address = AddressSerializerField()

    class Meta:
        model = Erc20Token
        fields = read_only_fields = TokenSerializer.Meta.read_only_fields + (
            "chain_id",
            "address",
        )


__all__ = ["NativeTokenSerializer", "Erc20TokenSerializer"]
