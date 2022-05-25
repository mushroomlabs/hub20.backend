import logging

from rest_framework import serializers

from hub20.apps.core.serializers import (
    AddressSerializerField,
    HexadecimalField,
    HyperlinkedRelatedTokenField,
    PaymentRouteSerializer,
    PaymentSerializer,
    TokenSerializer,
    TokenValueField,
)

from .analytics import estimate_gas_price
from .models import (
    BlockchainPayment,
    BlockchainPaymentRoute,
    Chain,
    Erc20Token,
    NativeToken,
    Wallet,
    WalletBalanceRecord,
)

logger = logging.getLogger(__name__)


class ChainSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="blockchain:chain-detail")
    token = serializers.CharField(source="native_token.symbol", read_only=True)
    explorers = serializers.SerializerMethodField()
    status = serializers.HyperlinkedIdentityField(view_name="blockchain:chain-status")

    def get_explorers(self, obj):
        return obj.explorers.values_list("url", flat=True)

    class Meta:
        model = Chain
        fields = read_only_fields = (
            "url",
            "id",
            "name",
            "short_name",
            "token",
            "explorers",
            "status",
        )


class ChainStatusSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="blockchain:chain-status")
    chain = serializers.HyperlinkedIdentityField(view_name="blockchain:chain-detail")
    height = serializers.IntegerField(source="highest_block", read_only=True)
    online = serializers.BooleanField(source="provider.connected")
    synced = serializers.BooleanField(source="provider.synced")
    gas_price_estimate = serializers.SerializerMethodField()

    def get_gas_price_estimate(self, obj):
        return estimate_gas_price(obj.id)

    class Meta:
        model = Chain
        fields = read_only_fields = (
            "url",
            "chain",
            "height",
            "online",
            "synced",
            "gas_price_estimate",
        )


class NativeTokenSerializer(TokenSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(queryset=Chain.active.all())

    class Meta:
        model = NativeToken
        fields = read_only_fields = (
            "symbol",
            "name",
            "chain_id",
            "decimals",
            "logoURI",
        )


class Erc20TokenSerializer(TokenSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(queryset=Chain.active.all())
    address = AddressSerializerField()

    class Meta:
        model = Erc20Token
        fields = read_only_fields = (
            "symbol",
            "name",
            "address",
            "chain_id",
            "decimals",
            "logoURI",
        )


class BlockchainPaymentSerializer(PaymentSerializer):
    transaction = HexadecimalField(source="transaction.hash", read_only=True)
    block = serializers.IntegerField(source="transaction.block.number", read_only=True)

    class Meta:
        model = BlockchainPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "transaction", "block")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "transaction",
            "block",
        )


class BlockchainPaymentRouteSerializer(PaymentRouteSerializer):
    address = AddressSerializerField(source="account.address", read_only=True)
    expiration_block = serializers.IntegerField(source="expiration_block_number", read_only=True)

    class Meta:
        model = BlockchainPaymentRoute
        fields = PaymentRouteSerializer.Meta.fields + (
            "address",
            "expiration_block",
        )
        read_only_fields = PaymentRouteSerializer.Meta.read_only_fields + (
            "address",
            "expiration_block",
        )


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
