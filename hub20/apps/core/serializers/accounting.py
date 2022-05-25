from rest_framework import serializers
from rest_framework.reverse import reverse

from ..models import Credit, Debit, PaymentConfirmation, Transfer, TransferConfirmation
from .tokens import (
    HyperlinkedTokenIdentityField,
    HyperlinkedTokenMixin,
    TokenSerializer,
    TokenValueField,
)


class HyperlinkedBalanceIdentityField(serializers.HyperlinkedIdentityField):
    def __init__(self, *args, **kw):
        kw.setdefault("view_name", "balance-detail")
        super().__init__(*args, **kw)

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)


class TokenBalanceSerializer(TokenSerializer):
    token = HyperlinkedTokenIdentityField(view_name="token-detail")
    amount = TokenValueField(read_only=True, source="balance")

    class Meta:
        model = TokenSerializer.Meta.model
        fields = read_only_fields = (
            "token",
            "amount",
        )


class HyperlinkedTokenBalanceSerializer(HyperlinkedTokenMixin, TokenBalanceSerializer):
    url = HyperlinkedTokenIdentityField(view_name="balance-detail")

    view_name = "balance-detail"

    class Meta:
        model = TokenBalanceSerializer.Meta.model
        fields = ("url",) + TokenBalanceSerializer.Meta.fields
        read_only_fields = ("url",) + TokenBalanceSerializer.Meta.read_only_fields


class AccountingBookSerializer(serializers.Serializer):
    token = HyperlinkedTokenIdentityField(view_name="token-detail", source="*")
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
            Transfer: "transfer",
            TransferConfirmation: "transfer sent",
            PaymentConfirmation: "payment received",
        }.get(type(obj.reference))

    def get_reference(self, obj):
        params = {
            TransferConfirmation: lambda: {
                "viewname": "transfer-detail",
                "kwargs": {"pk": obj.reference.transfer.pk},
            },
            PaymentConfirmation: lambda: {
                "viewname": "payments-detail",
                "kwargs": {"pk": obj.reference.payment.pk},
            },
            Transfer: lambda: {
                "viewname": "transfer-detail",
                "kwargs": {"pk": obj.reference.pk},
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
