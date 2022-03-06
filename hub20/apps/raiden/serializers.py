from django_celery_results.models import TaskResult
from raiden_contracts.contract_manager import gas_measurements
from rest_framework import serializers
from rest_framework_nested.relations import (
    NestedHyperlinkedIdentityField,
    NestedHyperlinkedRelatedField,
)
from rest_framework_nested.serializers import NestedHyperlinkedModelSerializer

from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import Web3Provider
from hub20.apps.ethereum_money.client import get_account_balance
from hub20.apps.ethereum_money.models import EthereumTokenAmount
from hub20.apps.ethereum_money.serializers import HyperlinkedRelatedTokenField, TokenValueField
from hub20.apps.ethereum_money.typing import TokenAmount

from . import models, tasks
from .client import RaidenClient, get_service_token


class ChainField(serializers.PrimaryKeyRelatedField):
    queryset = models.Chain.objects.filter(tokens__tokennetwork__isnull=False).distinct()


class TokenNetworkField(serializers.RelatedField):
    queryset = models.TokenNetwork.objects.all()
    lookup_field = "address"


class TokenNetworkSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="token-network-detail",
        lookup_field="address",
    )
    token = HyperlinkedRelatedTokenField()

    class Meta:
        model = models.TokenNetwork
        fields = ("url", "address", "token")
        read_only_fields = ("url", "address", "token")


class ChannelSerializer(NestedHyperlinkedModelSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="raiden-channel-detail",
        parent_lookup_kwargs={
            "raiden_pk": "raiden_id",
        },
    )
    token = HyperlinkedRelatedTokenField(read_only=True, queryset=None)

    class Meta:
        model = models.Channel
        fields = ("url", "id", "token", "identifier", "partner_address", "status", "balance")
        read_only_fields = (
            "url",
            "id",
            "token",
            "identifier",
            "partner_address",
            "status",
            "balance",
        )


class UserDepositSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField()
    total_deposit = TokenValueField()
    balance = TokenValueField()

    class Meta:
        model = models.UserDeposit
        fields = read_only_fields = ("token", "total_deposit", "balance")


class RaidenSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="raiden-detail")
    hostname = serializers.CharField()
    chain = serializers.HyperlinkedRelatedField(
        view_name="blockchain:chain-detail", read_only=True
    )
    channels = ChannelSerializer(many=True)
    token_networks = TokenNetworkSerializer(many=True)
    service_deposit_balance = UserDepositSerializer(source="udc")
    status = serializers.HyperlinkedIdentityField(view_name="raiden-status")

    class Meta:
        model = models.Raiden
        fields = read_only_fields = (
            "url",
            "id",
            "hostname",
            "chain",
            "address",
            "token_networks",
            "channels",
            "service_deposit_balance",
            "status",
        )


class RaidenStatusSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="raiden-status")
    raiden = serializers.HyperlinkedIdentityField(view_name="raiden-detail")
    online = serializers.SerializerMethodField()
    cost_estimates = serializers.SerializerMethodField()

    def get_online(self, obj):
        client = RaidenClient(raiden_node=obj)
        return "ready" == client.get_status()

    def get_cost_estimates(self, obj):
        try:
            provider = Web3Provider.active.get(chain_id=obj.chain.id)
            w3 = make_web3(provider=provider)
            gas_price = w3.eth.generate_gas_price()
            gas_costs = gas_measurements()
            actions = {
                "udc-deposit": gas_costs["UserDeposit.deposit"],
                "udc-topup": gas_costs["UserDeposit.deposit (increase balance)"],
                "udc-withdraw": (
                    gas_costs["UserDeposit.planWithdraw"] + gas_costs["UserDeposit.withdraw"]
                ),
                "channel-setup": gas_costs["TokenNetwork.openChannelWithDeposit"],
                "channel-open": gas_costs["TokenNetwork.openChannel"],
                "channel-deposit": gas_costs["TokenNetwork.setTotalDeposit"],
                "channel-withdraw": gas_costs["TokenNetwork.setTotalWithdraw"],
                "channel-close": gas_costs["TokenNetwork.closeChannel"],
            }
            return {k: gas_price and (v * gas_price) for k, v in actions.items()}
        except Web3Provider.DoesNotExist:
            return None

    class Meta:
        model = models.Raiden
        fields = read_only_fields = ("url", "raiden", "online", "cost_estimates")


class ManagementTaskSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="task_name")
    created = serializers.DateTimeField(source="date_created")
    completed = serializers.DateTimeField(source="date_done")

    class Meta:
        model = TaskResult
        fields = read_only_fields = ("task_id", "name", "status", "created", "completed", "result")


class ManagementOrderSerializer(serializers.ModelSerializer):
    raiden = serializers.HyperlinkedRelatedField(
        view_name="raiden-detail", queryset=models.Raiden.objects.all()
    )
    task = ManagementTaskSerializer(source="task_result", read_only=True)

    def get_task(self):
        try:
            return self.Meta.task
        except AttributeError:
            raise NotImplementedError

    def get_task_params(self, validated_data):
        raiden = validated_data["raiden"]
        return dict(raiden_url=raiden.url)

    def get_order_params(self, validated_data):
        return validated_data

    def create(self, validated_data):
        task = self.get_task().delay(**self.get_task_params(validated_data))
        result = TaskResult.objects.get_task(task.id)
        result.save()

        return self.Meta.model.objects.create(
            task_result=result, **self.get_order_params(validated_data)
        )

    def validate(self, data):
        raiden = self.get_raiden()

        if self.Meta.model.objects.filter(raiden=raiden, task_result__status="PENDING").exists():
            raise serializers.ValidationError("Another similar operation is pending execution")

        data["raiden"] = raiden

        return data

    def get_raiden(self):
        view = self.context["view"]
        return models.Raiden.objects.filter(id=view.kwargs["raiden_pk"]).first()

    class Meta:
        model = models.RaidenManagementOrder
        fields = ("raiden", "task")
        read_only_fields = ("task",)


class ServiceDepositSerializer(ManagementOrderSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="service-deposit-detail",
        parent_lookup_kwargs={
            "raiden_pk": "raiden_id",
        },
    )
    raiden = serializers.HyperlinkedRelatedField(view_name="raiden-detail", read_only=True)
    amount = TokenValueField()

    def get_task_params(self, validated_data):
        raiden = validated_data["raiden"]
        return dict(raiden_url=raiden.url, amount=validated_data["amount"])

    def get_order_params(self, validated_data):
        raiden = validated_data["raiden"]
        w3 = make_web3(provider=raiden.chain.provider)
        return dict(currency=get_service_token(w3=w3), **validated_data)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Need to deposit a value larger than 0")

        return value

    def validate(self, data):
        data = super().validate(data)

        raiden = data["raiden"]

        w3 = make_web3(provider=raiden.chain.provider)
        token = get_service_token(w3=w3)

        deposit_amount = EthereumTokenAmount(currency=token, amount=data["amount"])
        balance = get_account_balance(w3=w3, token=token, address=raiden.address)

        if balance < deposit_amount:
            raise serializers.ValidationError(f"Insufficient balance: {balance}")

        return data

    class Meta:
        model = models.UserDepositContractOrder
        fields = ("url", "created", "raiden", "amount", "task")
        read_only_fields = ("url", "created", "raiden", "task")
        task = tasks.make_udc_deposit


class ChannelManagementSerializer(ManagementOrderSerializer, NestedHyperlinkedModelSerializer):
    parent_lookup_kwargs = {"raiden_pk": "channel__raiden_id", "channel_pk": "channel_id"}

    channel = NestedHyperlinkedRelatedField(
        view_name="raiden-channel-detail",
        parent_lookup_kwargs={"raiden_pk": "raiden_id"},
        read_only=True,
    )
    amount = TokenValueField()

    def get_task_params(self, validated_data):
        channel = validated_data["channel"]
        return dict(channel_id=channel.id, deposit_amount=validated_data["amount"])

    def validate(self, data):
        data = super().validate(data)
        channel = self.get_channel()
        if channel is None:
            raise serializers.ValidationError("Can not get channel information")
        data["channel"] = channel
        return data

    def get_channel(self):
        view = self.context["view"]

        return models.Channel.objects.filter(
            raiden_id=view.kwargs["raiden_pk"], pk=view.kwargs["channel_pk"]
        ).first()

    class Meta:
        fields = ("url", "id", "created", "channel", "amount", "task")
        read_only_fields = ("url", "id", "created", "channel", "task")


class ChannelDepositSerializer(ChannelManagementSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="raiden-channel-deposit-detail",
        parent_lookup_kwargs=ChannelManagementSerializer.parent_lookup_kwargs,
    )

    class Meta:
        model = models.ChannelDepositOrder
        fields = ChannelManagementSerializer.Meta.fields
        read_only_fields = ChannelManagementSerializer.Meta.read_only_fields
        task = tasks.make_channel_deposit


class ChannelWithdrawalSerializer(ChannelManagementSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="raiden-channel-withdrawal-detail",
        parent_lookup_kwargs={"raiden_pk": "channel__raiden_id", "channel_pk": "channel_id"},
    )

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

    class Meta:
        model = models.ChannelWithdrawOrder
        fields = ChannelManagementSerializer.Meta.fields
        read_only_fields = ChannelManagementSerializer.Meta.read_only_fields
        task = tasks.make_channel_withdraw


class JoinTokenNetworkOrderSerializer(ManagementOrderSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="raiden-token-network-detail",
        lookup_field="address",
        parent_lookup_kwargs={
            "raiden_pk": "raiden_id",
        },
    )

    token_network = serializers.HyperlinkedRelatedField(
        view_name="token-network-detail",
        lookup_field="address",
        queryset=models.TokenNetwork.objects.all(),
    )

    def validate(self, validated_data):
        validated_data = super(validated_data)
        token_network = validated_data["token_network"]
        raiden = validated_data["raiden"]

        if token_network.chain_id != raiden.chain_id:
            raise serializers.ValidationError(
                f"Token network {token_network.address} is on {token_network.chain.name}"
                f" and Raiden at {raiden.url} is on {raiden.chain.name}"
            )

        if token_network in raiden.token_networks:
            raise serializers.ValidationError(
                f"Already joined token network {token_network.address}"
            )

        return validated_data

    class Meta:
        model = models.JoinTokenNetworkOrder
        fields = ("url", "created", "raiden", "token_network", "amount", "result")
        read_only_fields = ("url", "created", "raiden", "result")
