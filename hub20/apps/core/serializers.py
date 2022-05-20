from rest_framework import serializers

from hub20.apps.core.models import Token
from hub20.apps.core.serializers import AddressSerializerField
from hub20.apps.ethereum_money.serializers import (
    HyperlinkedRelatedTokenField,
    HyperlinkedTokenIdentityField,
    HyperlinkedTokenMixin,
    TokenSerializer,
    TokenValueField,
)

from . import models


class TokenRouteDescriptorSerializer(HyperlinkedTokenMixin, TokenSerializer):
    url = HyperlinkedTokenIdentityField(view_name="token-routes")
    token = HyperlinkedTokenIdentityField(view_name="token-detail")
    blockchain = serializers.HyperlinkedRelatedField(
        view_name="blockchain:chain-detail", source="chain_id", read_only=True
    )
    networks = serializers.SerializerMethodField()

    def get_networks(self, obj):
        return {"raiden": hasattr(obj, "tokennetwork")}

    class Meta:
        model = TokenSerializer.Meta.model
        fields = ("url", "token", "blockchain", "networks")
        read_only_fields = ("url", "token", "blockchain", "networks")
