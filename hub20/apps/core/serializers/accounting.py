from rest_framework import serializers
from rest_framework.reverse import reverse

from ..models import (
    Credit,
    Debit,
    InternalTransfer,
    PaymentConfirmation,
    Transfer,
    TransferConfirmation,
)
from .tokens import TokenSerializer, TokenValueField


class HyperlinkedBalanceIdentityField(serializers.HyperlinkedIdentityField):
    def __init__(self, *args, **kw):
        kw.setdefault("view_name", "balance-detail")
        super().__init__(*args, **kw)

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)


class TokenBalanceSerializer(TokenSerializer):
    token = serializers.HyperlinkedIdentityField(view_name="token-detail")
    amount = TokenValueField(read_only=True, source="balance")

    class Meta:
        model = TokenSerializer.Meta.model
        fields = read_only_fields = (
            "token",
            "amount",
        )


class HyperlinkedTokenBalanceSerializer(TokenBalanceSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="balance-detail")

    view_name = "balance-detail"

    class Meta:
        model = TokenBalanceSerializer.Meta.model
        fields = ("url",) + TokenBalanceSerializer.Meta.fields
        read_only_fields = ("url",) + TokenBalanceSerializer.Meta.read_only_fields


class AccountingBookSerializer(serializers.Serializer):
    token = serializers.HyperlinkedIdentityField(view_name="token-detail", source="*")
    total_credit = TokenValueField(read_only=True)
    total_debit = TokenValueField(read_only=True)
    balance = TokenValueField(read_only=True)


class BookEntrySerializer(serializers.ModelSerializer):
    amount = serializers.CharField(source="as_token_amount")
    reference_type = serializers.CharField(source="reference_type.model")
    reference = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    def get_type(self, obj):
        return obj.__class__.__name__.lower()

    def get_summary(self, obj):
        return {
            InternalTransfer: "Internal Transfer",
            Transfer: "Withdrawal",
            TransferConfirmation: "Received Transfer",
            PaymentConfirmation: "Received Payment",
        }.get(type(obj.reference))

    def get_reference(self, obj):
        params = {
            Transfer: lambda: {
                "viewname": "user-transfer-detail",
                "kwargs": {"pk": obj.reference.pk},
            },
            TransferConfirmation: lambda: {
                "viewname": "user-transfer-detail",
                "kwargs": {"pk": obj.reference.transfer.pk},
            },
            PaymentConfirmation: lambda: {
                "viewname": "payments-detail",
                "kwargs": {"pk": obj.reference.payment.pk},
            },
        }.get(type(obj.reference))

        return params and reverse(request=self.context.get("request"), **params())

    class Meta:
        read_only_fields = fields = (
            "id",
            "created",
            "amount",
            "type",
            "reference_type",
            "reference",
        )


class CreditSerializer(BookEntrySerializer):
    class Meta:
        model = Credit
        fields = read_only_fields = BookEntrySerializer.Meta.fields


class DebitSerializer(BookEntrySerializer):
    class Meta:
        model = Debit
        fields = read_only_fields = BookEntrySerializer.Meta.fields


__all__ = [
    "TokenBalanceSerializer",
    "HyperlinkedTokenBalanceSerializer",
    "AccountingBookSerializer",
    "BookEntrySerializer",
    "CreditSerializer",
    "DebitSerializer",
]
