from rest_framework import serializers
from rest_framework.reverse import reverse
from taggit.serializers import TaggitSerializer, TagListSerializerField

from .. import models


class TokenValueField(serializers.DecimalField):
    def __init__(self, *args, **kw):
        kw.setdefault("max_digits", 32)
        kw.setdefault("decimal_places", 18)
        super().__init__(*args, **kw)


class HyperlinkedTokenMixin:
    def get_queryset(self):
        return models.BaseToken.tradeable.all()

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)

    def get_object(self, view_name, view_args, view_kwargs):
        lookup_kwargs = {"chain_id": view_kwargs["chain_id"], "address": view_kwargs["address"]}
        queryset = self.get_queryset()
        return queryset.get(**lookup_kwargs)


class HyperlinkedRelatedTokenField(HyperlinkedTokenMixin, serializers.HyperlinkedRelatedField):
    queryset = models.BaseToken.tradeable.all()
    view_name = "token-detail"

    def get_attribute(self, instance):
        return getattr(instance, self.source)


class HyperlinkedTokenIdentityField(serializers.HyperlinkedIdentityField):
    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)


class TokenSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="token-detail")

    class Meta:
        model = models.BaseToken
        fields = read_only_fields = (
            "symbol",
            "name",
            "decimals",
            "logoURI",
        )


class TokenAmountSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    amount = TokenValueField()


class HyperlinkedTokenSerializer(TokenSerializer):
    url = HyperlinkedTokenIdentityField(view_name="token-detail")

    class Meta:
        model = models.BaseToken
        fields = ("url",) + TokenSerializer.Meta.fields
        read_only_fields = ("url",) + TokenSerializer.Meta.read_only_fields


class TokenInfoSerializer(serializers.ModelSerializer):
    wrapped_by = HyperlinkedTokenIdentityField(view_name="token-detail", read_only=True, many=True)
    wraps = HyperlinkedRelatedTokenField()

    class Meta:
        model = models.BaseToken
        fields = read_only_fields = (
            "name",
            "symbol",
            "wrapped_by",
            "wraps",
            "is_stable",
            "tracks_currency",
        )


class BaseTokenListSerializer(serializers.ModelSerializer):
    tokens = HyperlinkedRelatedTokenField(many=True)


class TokenListSerializer(TaggitSerializer, BaseTokenListSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="tokenlist-detail")
    source = serializers.URLField(source="url")
    keywords = TagListSerializerField(read_only=True)

    class Meta:
        model = models.TokenList
        fields = read_only_fields = (
            "url",
            "id",
            "version",
            "source",
            "name",
            "description",
            "tokens",
            "keywords",
        )


class UserTokenListSerializer(BaseTokenListSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-tokenlist-detail")
    keywords = TagListSerializerField()

    def create(self, validated_data):
        request = self.context.get("request")
        tokens = validated_data.pop("tokens")
        user_token_list = request.user.token_lists.create(**validated_data)
        user_token_list.tokens.set(tokens)
        return user_token_list

    class Meta:
        model = models.UserTokenList
        fields = ("url", "id", "name", "description", "tokens", "keywords")
        read_only_fields = ("url", "id")


class TokenListImportSerializer(serializers.ModelSerializer):
    url = serializers.URLField()

    def validate(self, data):
        url = data["url"]
        try:
            token_list_data = models.TokenList.fetch(url)
        except ValueError as exc:
            raise serializers.ValidationError(exc)

        data.update({"token_list_data": token_list_data})
        return data

    class Meta:
        model = models.TokenList
        fields = ("url", "description")


class UserTokenListCloneSerializer(UserTokenListSerializer):
    token_list = serializers.HyperlinkedRelatedField(
        view_name="tokenlist-detail", queryset=models.TokenList.objects.all(), write_only=True
    )

    def create(self, validated_data):
        request = self.context["request"]
        return models.UserTokenList.clone(
            user=request.user, token_list=validated_data["token_list"]
        )

    class Meta:
        model = models.UserTokenList
        fields = UserTokenListSerializer.Meta.fields + ("token_list",)
        read_only_fields = ("url", "name", "description", "tokens", "keywords")
