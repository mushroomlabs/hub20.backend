from rest_framework import serializers

from ..models import Store
from .tokens import HyperlinkedTokenSerializer


class StoreAcceptedTokenListSelectorField(serializers.HyperlinkedRelatedField):
    view_name = "user-tokenlist-detail"

    def get_queryset(self):
        request = self.context.get("request")

        return request.user.token_lists.all()


class StoreSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="store-detail")
    site_url = serializers.URLField(source="url")
    public_key = serializers.CharField(source="rsa.public_key_pem", read_only=True)

    class Meta:
        model = Store
        fields = ("id", "url", "name", "site_url", "public_key")
        read_only_fields = ("id", "public_key")


class StoreEditorSerializer(StoreSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-store-detail")
    accepted_token_list = StoreAcceptedTokenListSelectorField()
    checkout_webhook_url = serializers.URLField(allow_null=True, required=False)

    def create(self, validated_data):
        request = self.context.get("request")
        return Store.objects.create(owner=request.user, **validated_data)

    class Meta:
        model = Store
        fields = StoreSerializer.Meta.fields + (
            "accepted_token_list",
            "checkout_webhook_url",
        )
        read_only_fields = StoreSerializer.Meta.read_only_fields


class StoreViewerSerializer(StoreSerializer):
    accepted_currencies = HyperlinkedTokenSerializer(many=True)

    class Meta:
        model = Store
        fields = read_only_fields = (
            "id",
            "url",
            "name",
            "site_url",
            "public_key",
            "accepted_currencies",
        )


__all__ = ["StoreSerializer", "StoreEditorSerializer", "StoreViewerSerializer"]
