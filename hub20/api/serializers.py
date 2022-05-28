from dj_rest_auth.serializers import UserDetailsSerializer
from rest_framework import serializers

from hub20.apps.core.models import PaymentNetwork
from hub20.apps.core.serializers import TokenSerializer


class UserProfileSerializer(UserDetailsSerializer):
    has_admin_access = serializers.BooleanField(source="is_staff", read_only=True)

    class Meta:
        model = UserDetailsSerializer.Meta.model
        fields = UserDetailsSerializer.Meta.fields + ("has_admin_access",)
        read_only_fields = UserDetailsSerializer.Meta.read_only_fields + ("has_admin_access",)


class TokenRouteDescriptorSerializer(TokenSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="token-routes")
    token = serializers.HyperlinkedIdentityField(view_name="token-detail")
    blockchain = serializers.HyperlinkedRelatedField(
        view_name="blockchain:chain-detail", source="chain_id", read_only=True
    )
    networks = serializers.SerializerMethodField()

    def get_networks(self, obj):
        return [
            network.id
            for network in PaymentNetwork.objects.all().select_subclasses()
            if network.supports_token(obj)
        ]

    class Meta:
        model = TokenSerializer.Meta.model
        fields = ("url", "token", "blockchain", "networks")
        read_only_fields = ("url", "token", "blockchain", "networks")
