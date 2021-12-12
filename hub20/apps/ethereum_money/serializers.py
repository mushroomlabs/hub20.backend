from rest_framework import serializers
from rest_framework.reverse import reverse

from hub20.apps.blockchain.serializers import EthereumAddressField

from . import get_ethereum_account_model, models


class TokenValueField(serializers.DecimalField):
    def __init__(self, *args, **kw):
        kw.setdefault("max_digits", 32)
        kw.setdefault("decimal_places", 18)
        super().__init__(*args, **kw)


class HyperlinkedRelatedTokenField(serializers.HyperlinkedRelatedField):
    view_name = "ethereum_money:token-detail"
    queryset = models.EthereumToken.tracked.all()

    def get_attribute(self, instance):
        return getattr(instance, self.source)

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)

    def get_object(self, view_name, view_args, view_kwargs):
        lookup_kwargs = {"chain_id": view_kwargs["chain_id"], "address": view_kwargs["address"]}
        return self.queryset.get(**lookup_kwargs)


class HyperlinkedTokenIdentityField(serializers.HyperlinkedIdentityField):
    def __init__(self, *args, **kw):
        kw.setdefault("view_name", "ethereum_money:token-detail")
        super().__init__(*args, **kw)

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)


class EthereumTokenSerializer(serializers.ModelSerializer):
    network_id = serializers.IntegerField(source="chain_id")

    class Meta:
        model = models.EthereumToken
        fields = ("code", "name", "address", "network_id", "decimals")
        read_only_fields = ("code", "name", "address", "network_id", "decimals")


class EthereumTokenAmountSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    amount = TokenValueField()


class HyperlinkedEthereumTokenSerializer(EthereumTokenSerializer):
    url = HyperlinkedTokenIdentityField()

    class Meta:
        model = models.EthereumToken
        fields = ("url",) + EthereumTokenSerializer.Meta.fields
        read_only_fields = ("url",) + EthereumTokenSerializer.Meta.read_only_fields


class EthereumAccountSerializer(serializers.ModelSerializer):
    address = EthereumAddressField()

    class Meta:
        model = get_ethereum_account_model()
        fields = read_only_fields = ("address",)
