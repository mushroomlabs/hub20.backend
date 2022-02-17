from rest_framework import serializers

from hub20.apps.blockchain.serializers import EthereumAddressField
from hub20.apps.ethereum_money.serializers import HyperlinkedRelatedTokenField, TokenValueField

from . import models


class WalletBalanceSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    balance = TokenValueField(source="amount")
    block = serializers.IntegerField(source="block.number", read_only=True)

    class Meta:
        model = models.WalletBalanceRecord
        fields = read_only_fields = ("token", "balance", "block")


class WalletSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="wallet-detail", lookup_field="address")

    address = EthereumAddressField(read_only=True)
    balances = WalletBalanceSerializer(many=True, read_only=True)

    class Meta:
        model = models.Wallet
        fields = read_only_fields = ("url", "address", "balances")
