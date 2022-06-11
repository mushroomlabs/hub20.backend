from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import BaseToken
from .tokens import HyperlinkedRelatedTokenField, TokenSerializer

User = get_user_model()


class UserRelatedField(serializers.SlugRelatedField):
    queryset = User.objects.filter(is_active=True)

    def __init__(self, *args, **kw):
        kw.setdefault("slug_field", "username")
        super().__init__(*args, **kw)


class UserTokenSelectorField(HyperlinkedRelatedTokenField):
    def get_attribute(self, instance):
        return instance


class UserSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="users-detail", lookup_field="username")

    class Meta:
        model = User
        fields = read_only_fields = ("url", "username", "first_name", "last_name", "email")


class UserTokenSerializer(TokenSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-token-detail")
    token = serializers.HyperlinkedIdentityField(view_name="token-detail", read_only=True)

    class Meta:
        model = TokenSerializer.Meta.model
        fields = ("url", "token") + TokenSerializer.Meta.fields
        read_only_fields = ("url", "token") + TokenSerializer.Meta.fields


class UserTokenCreatorSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-token-detail")
    token = UserTokenSelectorField(view_name="token-detail", queryset=BaseToken.tradeable.all())

    def validate(self, data):
        token = data["token"]
        if not token.is_listed:
            raise serializers.ValidationError(f"Token {token} is not listed for trading")
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
