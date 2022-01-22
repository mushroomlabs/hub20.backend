from rest_framework import serializers
from rest_framework.reverse import reverse

from . import models


class TokenValueField(serializers.DecimalField):
    def __init__(self, *args, **kw):
        kw.setdefault("max_digits", 32)
        kw.setdefault("decimal_places", 18)
        super().__init__(*args, **kw)


class HyperlinkedTokenMixin:
    queryset = models.EthereumToken.objects.filter(chain__providers__is_active=True)

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)

    def get_object(self, view_name, view_args, view_kwargs):
        lookup_kwargs = {"chain_id": view_kwargs["chain_id"], "address": view_kwargs["address"]}
        return self.queryset.get(**lookup_kwargs)


class HyperlinkedRelatedTokenField(HyperlinkedTokenMixin, serializers.HyperlinkedRelatedField):
    view_name = "token-detail"

    def get_attribute(self, instance):
        return getattr(instance, self.source)


class HyperlinkedTokenIdentityField(serializers.HyperlinkedIdentityField):
    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)


class EthereumTokenSerializer(serializers.ModelSerializer):
    network_id = serializers.IntegerField(source="chain_id", read_only=True)

    class Meta:
        model = models.EthereumToken
        fields = read_only_fields = (
            "symbol",
            "name",
            "address",
            "network_id",
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


class TokenListSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="tokenlist-detail")
    tokens = HyperlinkedRelatedTokenField(many=True)

    class Meta:
        model = models.TokenList
        fields = ("url", "name", "description", "tokens")


class UserTokenListSerializer(serializers.Serializer):
    token_lists = serializers.HyperlinkedRelatedField(
        queryset=models.TokenList.objects.all(), view_name="tokenlist-detail", many=True
    )

    def create(self, validated_data):
        request = self.context.get("request")
        return self.Meta.model.objects.create(user=request.user, **validated_data)
