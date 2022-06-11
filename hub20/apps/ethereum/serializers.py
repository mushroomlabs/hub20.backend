import logging

from rest_framework import serializers

from hub20.apps.core.serializers import (
    AddressSerializerField,
    BaseWithdrawalSerializer,
    HexadecimalField,
    HyperlinkedRelatedTokenField,
    PaymentNetworkSerializer,
    PaymentNetworkStatusSerializer,
    PaymentRouteSerializer,
    PaymentSerializer,
    TokenSerializer,
    TokenValueField,
)
from hub20.apps.ethereum import get_wallet_model

from .analytics import estimate_gas_price
from .models import (
    BlockchainPayment,
    BlockchainPaymentNetwork,
    BlockchainPaymentRoute,
    BlockchainTransfer,
    Chain,
    Erc20Token,
    NativeToken,
    WalletBalanceRecord,
)

logger = logging.getLogger(__name__)

Wallet = get_wallet_model()


class NativeTokenSerializer(TokenSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(queryset=Chain.active.all())

    class Meta:
        model = NativeToken
        fields = read_only_fields = TokenSerializer.Meta.read_only_fields + ("chain_id",)


class Erc20TokenSerializer(TokenSerializer):
    chain_id = serializers.PrimaryKeyRelatedField(queryset=Chain.active.all())
    address = AddressSerializerField()

    class Meta:
        model = Erc20Token
        fields = read_only_fields = TokenSerializer.Meta.read_only_fields + (
            "chain_id",
            "address",
        )


class BlockchainWithdrawalSerializer(BaseWithdrawalSerializer):
    address = AddressSerializerField()

    class Meta:
        model = BlockchainTransfer
        fields = BaseWithdrawalSerializer.Meta.fields + ("address",)


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


class BlockchainPaymentNetworkSerializer(PaymentNetworkSerializer):
    short_name = serializers.CharField(source="chain.short_name")
    chain_id = serializers.IntegerField(source="chain.id")
    token = serializers.HyperlinkedRelatedField(
        view_name="token-detail", source="chain.native_token", read_only=True
    )

    class Meta:
        model = BlockchainPaymentNetwork
        fields = read_only_fields = PaymentNetworkSerializer.Meta.fields + (
            "short_name",
            "chain_id",
            "token",
        )


class BlockchainStatusSerializer(PaymentNetworkStatusSerializer):
    height = serializers.IntegerField(source="chain.highest_block", read_only=True)
    online = serializers.BooleanField(source="chain.provider.connected")
    synced = serializers.BooleanField(source="chain.provider.synced")
    gas_price_estimate = serializers.SerializerMethodField()

    def get_gas_price_estimate(self, obj):
        return estimate_gas_price(obj.chain_id)

    class Meta:
        model = BlockchainPaymentNetwork
        fields = read_only_fields = (
            "url",
            "height",
            "online",
            "synced",
            "gas_price_estimate",
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
