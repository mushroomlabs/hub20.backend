from rest_framework import serializers
from rest_framework.reverse import reverse
from taggit.serializers import TaggitSerializer, TagListSerializerField

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import Chain, Web3Provider
from hub20.apps.blockchain.serializers import EthereumAddressField

from . import models
from .client import get_token_information, get_transfer_gas_estimate


class TokenValueField(serializers.DecimalField):
    def __init__(self, *args, **kw):
        kw.setdefault("max_digits", 32)
        kw.setdefault("decimal_places", 18)
        super().__init__(*args, **kw)


class HyperlinkedTokenMixin:
    def get_queryset(self):
        return models.EthereumToken.tradeable.all()

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)

    def get_object(self, view_name, view_args, view_kwargs):
        lookup_kwargs = {"chain_id": view_kwargs["chain_id"], "address": view_kwargs["address"]}
        queryset = self.get_queryset()
        return queryset.get(**lookup_kwargs)


class HyperlinkedRelatedTokenField(HyperlinkedTokenMixin, serializers.HyperlinkedRelatedField):
    queryset = models.EthereumToken.tradeable.all()
    view_name = "token-detail"

    def get_attribute(self, instance):
        return getattr(instance, self.source)


class HyperlinkedTokenIdentityField(serializers.HyperlinkedIdentityField):
    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)


class EthereumTokenSerializer(serializers.ModelSerializer):
    address = EthereumAddressField()
    chain_id = serializers.PrimaryKeyRelatedField(queryset=Chain.active.all())

    def validate(self, data):
        chain = data.pop("chain_id")
        address = data.pop("address")

        if chain.tokens.filter(address=address).exists():
            raise serializers.ValidationError(f"Token {address} already registered")

        provider = Web3Provider.available.filter(chain_id=chain.id).first()
        if not provider:
            raise serializers.ValidationError(f"Could not query {chain.id} for token information")

        w3 = make_web3(provider=provider)
        try:
            token_data = get_token_information(w3, address=address)
        except Exception:
            raise serializers.ValidationError(
                f"Could not get token information for address {address}"
            )

        data.update(token_data)
        data.update({"chain": chain, "address": address})

        try:
            token = models.EthereumToken(**data)
            get_transfer_gas_estimate(w3=w3, token=token)
        except Exception:
            raise serializers.ValidationError(
                f"Could not verify {address} as a tradeable ERC20 token"
            )

        return data

    class Meta:
        model = models.EthereumToken
        fields = (
            "symbol",
            "name",
            "address",
            "chain_id",
            "decimals",
            "logoURI",
        )
        read_only_fields = (
            "symbol",
            "name",
            "decimals",
            "logoURI",
        )


class EthereumTokenAmountSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    amount = TokenValueField()


class HyperlinkedEthereumTokenSerializer(EthereumTokenSerializer):
    url = HyperlinkedTokenIdentityField(view_name="token-detail")

    class Meta:
        model = models.EthereumToken
        fields = ("url",) + EthereumTokenSerializer.Meta.fields
        read_only_fields = ("url",) + EthereumTokenSerializer.Meta.read_only_fields


class TokenInfoSerializer(serializers.ModelSerializer):
    wrapped_by = HyperlinkedTokenIdentityField(view_name="token-detail", read_only=True, many=True)
    wraps = HyperlinkedRelatedTokenField()

    class Meta:
        model = models.EthereumToken
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
