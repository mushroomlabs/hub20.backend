from raiden_contracts.contract_manager import gas_measurements
from rest_framework import serializers
from rest_framework_nested.relations import NestedHyperlinkedIdentityField
from rest_framework_nested.serializers import NestedHyperlinkedModelSerializer

from hub20.apps.core.serializers import HyperlinkedRelatedTokenField, PaymentSerializer
from hub20.apps.web3.client import make_web3
from hub20.apps.web3.models import Web3Provider

from . import models
from .client import RaidenClient


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


class RaidenPaymentSerializer(PaymentSerializer):
    raiden = serializers.CharField(source="payment.channel.raiden.address")

    class Meta:
        model = models.RaidenPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "raiden")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "raiden",
        )
