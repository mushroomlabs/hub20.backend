from rest_framework import serializers
from rest_framework_nested.relations import NestedHyperlinkedIdentityField
from rest_framework_nested.serializers import NestedHyperlinkedModelSerializer

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.serializers import HexadecimalField
from hub20.apps.ethereum_money.app_settings import TRACKED_TOKENS
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.ethereum_money.serializers import (
    EthereumTokenSerializer,
    HyperlinkedEthereumTokenSerializer,
    TokenValueField,
)
from hub20.apps.ethereum_money.typing import TokenAmount

from . import models
from .client.blockchain import get_service_token, get_service_token_contract
from .client.node import RaidenClient


class ChainField(serializers.PrimaryKeyRelatedField):
    queryset = models.Chain.active.all().order_by("id")


class TokenNetworkField(serializers.RelatedField):
    queryset = models.TokenNetwork.objects.filter(token__address__in=TRACKED_TOKENS)
    lookup_field = "address"


class TokenNetworkSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="token-network-detail", lookup_field="address"
    )
    token = HyperlinkedEthereumTokenSerializer()

    class Meta:
        model = models.TokenNetwork
        fields = ("url", "address", "token")
        read_only_fields = ("url", "address", "token")


class ServiceDepositSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="service-deposit-detail")
    raiden = serializers.HyperlinkedRelatedField(
        view_name="raiden-detail", queryset=models.Raiden.objects.all()
    )
    transaction = HexadecimalField(read_only=True, source="result.transaction.hash")
    chain = ChainField(write_only=True)
    token = EthereumTokenSerializer(source="currency", read_only=True)
    amount = TokenValueField()
    error = serializers.CharField(source="error.message", read_only=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Need to deposit a value larger than 0")

        return value

    def validate(self, data):
        chain = data.pop("chain")
        w3 = make_web3(provider=chain.provider)
        token = get_service_token(w3=w3)
        raiden = data["raiden"]

        if chain not in raiden.chains:
            raise serializers.ValidationError(
                f"{raiden} does not seem to be connected to chain {chain.id}"
            )

        contract = get_service_token_contract(w3=w3)
        deposit_amount = EthereumTokenAmount(currency=token, amount=data["amount"])
        balance = token.from_wei(contract.functions.balanceOf(raiden.address).call())

        if balance < deposit_amount:
            raise serializers.ValidationError(f"Insufficient balance: {balance}")

        return data

    def create(self, validated_data):
        request = self.context.get("request")

        chain = validated_data.pop("chain")
        w3 = make_web3(provider=chain.provider)
        token = get_service_token(w3=w3)

        return self.Meta.model.objects.create(user=request.user, currency=token, **validated_data)

    class Meta:
        model = models.UserDepositContractOrder
        fields = ("url", "created", "raiden", "amount", "token", "chain", "transaction", "error")
        read_only_fields = ("url", "created", "raiden", "token", "transaction", "error")


class ChannelSerializer(NestedHyperlinkedModelSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="raiden-channels-detail",
        parent_lookup_kwargs={
            "raiden_pk": "raiden_id",
        },
    )
    token = HyperlinkedEthereumTokenSerializer(source="token_network.token", read_only=True)

    class Meta:
        model = models.Channel
        fields = ("url", "token", "identifier", "partner_address", "status", "balance")
        read_only_fields = ("url", "token", "identifier", "partner_address", "status", "balance")


class ChannelManagementSerializer(serializers.ModelSerializer):
    channel = serializers.HyperlinkedRelatedField(view_name="channel-detail", read_only=True)
    amount = TokenValueField()

    def create(self, validated_data):
        channel = self.get_channel()
        request = self.context["request"]

        return self.Meta.model.objects.create(
            raiden=channel.raiden, channel=channel, user=request.user, **validated_data
        )

    def get_channel(self):
        view = self.context.get("view")
        return view and view.get_object()


class ChannelDepositSerializer(ChannelManagementSerializer):
    class Meta:
        model = models.ChannelDepositOrder
        fields = ("id", "created", "channel", "amount")
        read_only_fields = ("id", "created", "channel")


class ChannelWithdrawSerializer(ChannelManagementSerializer):
    class Meta:
        model = models.ChannelWithdrawOrder
        fields = ("created", "channel", "amount")
        read_only_fields = ("created", "channel")

    def validate_amount(self, data):
        channel = self.get_channel()
        if channel is None:
            raise serializers.ValidationError("Can not get channel information")

        token = channel.token
        amount = TokenAmount(data).normalize()
        withdraw_amount = EthereumTokenAmount(amount=amount, currency=token)
        channel_balance = EthereumTokenAmount(amount=channel.balance, currency=token)

        if withdraw_amount > channel_balance:
            raise serializers.ValidationError(f"Insufficient balance: {channel_balance.formatted}")

        return data


class RaidenSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="raiden-detail")
    channels = ChannelSerializer(many=True)
    status = serializers.SerializerMethodField()

    def get_status(self, obj):
        client = RaidenClient(raiden_account=obj)
        return client.get_status()

    class Meta:
        model = models.Raiden
        fields = ("url", "address", "channels", "status")
        read_only_fields = ("url", "address", "channels", "status")


class JoinTokenNetworkOrderSerializer(serializers.ModelSerializer):
    token_network = serializers.HyperlinkedRelatedField(
        view_name="token-network-detail", lookup_field="address", read_only=True
    )

    def get_token_network(self):
        view = self.context.get("view")
        return view and view.get_object()

    def create(self, validated_data):
        request = self.context["request"]
        token_network = self.get_token_network()

        return self.Meta.model.objects.create(
            raiden=self.raiden, token_network=token_network, user=request.user, **validated_data
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        token_network = self.get_token_network()

        assert isinstance(self.raiden, models.Raiden)
        if token_network in self.raiden.token_networks:
            raise serializers.ValidationError(
                f"Already joined token network {token_network.address}"
            )

        return attrs

    class Meta:
        model = models.JoinTokenNetworkOrder
        fields = ("id", "created", "token_network", "amount")
        read_only_fields = ("id", "created", "token_network")
