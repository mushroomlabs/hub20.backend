from rest_framework import serializers

from ..models import (
    InternalPaymentNetwork,
    InternalTransfer,
    PaymentNetwork_T,
    TokenAmount,
    Transfer,
    TransferConfirmation,
)
from .base import PolymorphicModelSerializer
from .tokens import HyperlinkedRelatedTokenField, TokenValueField
from .users import UserRelatedField


class TransferSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    status = serializers.CharField(read_only=True)

    def validate(self, data):
        # We do need to check the balance here though because the amount
        # corresponding to the transfer is deducted from the user's balance
        # upon creation for two reasons: keeping the accounting books balanced
        # and ensuring that users can not overdraw.

        # There is also the cost of transfer fees (especially for on-chain
        # transfers), but given that these can not be predicted and the hub
        # operator might waive the fees from the users, we do not do any
        # charging here and deduct fees only after the transaction is complete.
        request = self.context["request"]

        currency = data["currency"]
        transfer_amount = TokenAmount(currency=currency, amount=data["amount"])
        user_balance_amount = request.user.account.get_balance_token_amount(currency)

        if not user_balance_amount:
            raise serializers.ValidationError("No balance available", code="invalid")

        if user_balance_amount < transfer_amount:
            raise serializers.ValidationError("Insufficient balance", code="insufficient")

        return data

    def create(self, validated_data):
        request = self.context["request"]

        return self.Meta.model.objects.create(sender=request.user, **validated_data)

    class Meta:
        model = Transfer
        fields = (
            "url",
            "amount",
            "token",
            "memo",
            "identifier",
            "status",
        )
        read_only_fields = (
            "url",
            "status",
        )


class BaseWithdrawalSerializer(TransferSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-withdrawal-detail")

    @classmethod
    def get_subclassed_serializer(cls, network: PaymentNetwork_T):
        """
        Each Transfer class needs to define its network type. With
        this, we can define what serializer to use for a withdrawal
        """
        return {c.Meta.model.NETWORK: c for c in cls.__subclasses__()}.get(type(network), cls)

    def create(self, validated_data):
        request = self.context["request"]
        view = self.context["view"]

        network = view.get_network()
        return self.Meta.model.objects.create(
            sender=request.user, network=network, **validated_data
        )

    class Meta:
        model = Transfer
        fields = TransferSerializer.Meta.fields
        read_only_fields = TransferSerializer.Meta.read_only_fields


class InternalTransferSerializer(TransferSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-transfer-detail")
    recipient = UserRelatedField(source="receiver")

    def validate_recipient(self, value):
        request = self.context["request"]
        if value == request.user:
            raise serializers.ValidationError("You can not make a transfer to yourself")
        return value

    def validate(self, data):
        data = super().validate(data)
        data["network"] = InternalPaymentNetwork.objects.first()
        return data

    def create(self, validated_data):
        request = self.context["request"]

        return self.Meta.model.objects.create(sender=request.user, **validated_data)

    class Meta:
        model = InternalTransfer
        fields = TransferSerializer.Meta.fields + ("recipient",)
        read_only_fields = TransferSerializer.Meta.read_only_fields


class TransferConfirmationSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="transfer.currency")
    target = serializers.CharField(source="transfer.target", read_only=True)
    amount = TokenValueField(source="transfer.amount")

    class Meta:
        model = TransferConfirmation
        fields = read_only_fields = ("created", "token", "amount", "target")


__all__ = [
    "TransferSerializer",
    "TransferConfirmationSerializer",
    "InternalTransferSerializer",
    "BaseWithdrawalSerializer",
]
