from raiden_contracts.contract_manager import gas_measurements
from rest_framework import serializers

from hub20.apps.core.serializers import PaymentSerializer
from hub20.apps.ethereum.client import make_web3
from hub20.apps.ethereum.models import Web3Provider

from . import models
from .client import RaidenClient


class RaidenSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="raiden-detail")
    hostname = serializers.CharField()
    chain = serializers.HyperlinkedRelatedField(
        view_name="blockchain:chain-detail", read_only=True
    )
    status = serializers.HyperlinkedIdentityField(view_name="raiden-status")

    class Meta:
        model = models.Raiden
        fields = read_only_fields = (
            "url",
            "id",
            "hostname",
            "chain",
            "address",
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


class RaidenPaymentSerializer(PaymentSerializer):
    raiden = serializers.CharField(source="payment.channel.raiden.address")

    class Meta:
        model = models.RaidenPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "raiden")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "raiden",
        )
