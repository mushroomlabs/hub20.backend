from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import BaseToken
from .fields import AddressSerializerField
from .tokens import (
    HyperlinkedRelatedTokenField,
    HyperlinkedTokenIdentityField,
    HyperlinkedTokenMixin,
    TokenSerializer,
)

User = get_user_model()


class UserRelatedField(serializers.SlugRelatedField):
    queryset = User.objects.filter(is_active=True)

    def __init__(self, *args, **kw):
        kw.setdefault("slug_field", "username")
        super().__init__(*args, **kw)


class UserTokenSelectorField(HyperlinkedRelatedTokenField, HyperlinkedTokenMixin):
    def get_attribute(self, instance):
        return instance


class UserSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="users-detail", lookup_field="username")

    class Meta:
        model = User
        fields = read_only_fields = ("url", "username", "first_name", "last_name", "email")


class UserTokenSerializer(TokenSerializer):
    url = HyperlinkedTokenIdentityField(view_name="user-token-detail")
    token = HyperlinkedTokenIdentityField(view_name="token-detail", read_only=True)
    address = AddressSerializerField(read_only=True)
    chain_id = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = TokenSerializer.Meta.model
        fields = ("url", "token") + TokenSerializer.Meta.fields
        read_only_fields = ("url", "token") + TokenSerializer.Meta.fields


class UserTokenCreatorSerializer(serializers.ModelSerializer):
    url = HyperlinkedTokenIdentityField(view_name="user-token-detail")
    token = UserTokenSelectorField(view_name="token-detail")

    def validate(self, data):
        token = data["token"]
        if not BaseToken.tradeable.filter(id=token.id).exists():
            raise serializers.ValidationError(
                f"Token {token.symbol} on chain #{token.chain_id} is not listed for trade"
            )
        return data

    def create(self, validated_data):
        request = self.context["request"]
        token = validated_data["token"]
        request.user.preferences.tokens.add(token)
        return token

    class Meta:
        model = TokenSerializer.Meta.model
        fields = ("url", "token") + TokenSerializer.Meta.fields
        read_only_fields = ("url",) + TokenSerializer.Meta.fields
