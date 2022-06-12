from rest_framework import serializers

from hub20.apps.core.serializers import HyperlinkedRelatedTokenField, TokenValueField
from hub20.apps.ethereum import get_wallet_model

from ..models import WalletBalanceRecord
from .fields import AddressSerializerField

Wallet = get_wallet_model()


class WalletBalanceSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    balance = TokenValueField(source="amount")
    block = serializers.IntegerField(source="block.number", read_only=True)

    class Meta:
        model = WalletBalanceRecord
        fields = read_only_fields = ("token", "balance", "block")


class WalletSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="wallet-detail", lookup_field="address")

    address = AddressSerializerField(read_only=True)
    balances = WalletBalanceSerializer(many=True, read_only=True)

    class Meta:
        model = Wallet
        fields = read_only_fields = ("url", "address", "balances")


__all__ = ["WalletBalanceSerializer", "WalletSerializer"]
