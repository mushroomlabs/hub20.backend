from rest_framework import serializers

from hub20.apps.core.tokens.serializers import (
    HyperlinkedTokenIdentityField,
    HyperlinkedTokenMixin,
    TokenSerializer,
)


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
