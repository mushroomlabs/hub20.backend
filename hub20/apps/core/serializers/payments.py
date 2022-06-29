from typing import Dict

from django.db import transaction
from rest_framework import serializers
from rest_framework_nested.relations import NestedHyperlinkedIdentityField
from rest_framework_nested.serializers import NestedHyperlinkedModelSerializer

from ..exceptions import RoutingError
from ..models import (
    Deposit,
    InternalPayment,
    InternalPaymentRoute,
    Payment,
    PaymentConfirmation,
    PaymentNetwork,
    PaymentOrder,
    PaymentRoute,
)
from .base import PolymorphicModelSerializer
from .tokens import HyperlinkedRelatedTokenField, TokenSerializer, TokenValueField


class PaymentRouteNetworkSelectorField(serializers.HyperlinkedRelatedField):
    def get_queryset(self):
        return PaymentNetwork.objects.filter(providers__is_active=True).select_subclasses()


class PaymentRouteSerializer(PolymorphicModelSerializer):
    network = PaymentRouteNetworkSelectorField(view_name="network-detail")

    class Meta:
        model = PaymentRoute
        fields = read_only_fields = (
            "id",
            "network",
            "identifier",
            "is_expired",
            "is_open",
            "is_used",
        )


class InternalPaymentRouteSerializer(PaymentRouteSerializer):
    class Meta:
        model = InternalPaymentRoute
        fields = read_only_fields = ("recipient",)


class PaymentSerializer(PolymorphicModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="payments-detail")
    network = serializers.HyperlinkedRelatedField(
        view_name="network-detail", source="route.network", read_only=True
    )
    currency = TokenSerializer()
    confirmed = serializers.BooleanField(source="is_confirmed", read_only=True)

    class Meta:
        model = Payment
        fields = read_only_fields = (
            "id",
            "url",
            "created",
            "network",
            "currency",
            "amount",
            "confirmed",
        )


class InternalPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "user", "memo")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "user",
            "memo",
        )


class DepositSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    routes = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    def create(self, validated_data: Dict):
        request = self.context["request"]
        with transaction.atomic():
            request.session.save()  # Ensure it has a key
            return self.Meta.model.objects.create(
                user=request.user, session_key=request.session.session_key, **validated_data
            )

    def get_routes(self, obj):
        def get_route_serializer(route):
            serializer_class = PaymentRouteSerializer.get_subclassed_serializer(route)
            return serializer_class(route, context=self.context)

        return [get_route_serializer(route).data for route in obj.routes.select_subclasses()]

    def get_payments(self, obj):
        def get_payment_serializer(payment):
            serializer_class = PaymentSerializer.get_subclassed_serializer(payment)
            return serializer_class(payment, context=self.context)

        return [get_payment_serializer(payment).data for payment in obj.payments]

    class Meta:
        model = Deposit
        fields = (
            "id",
            "token",
            "created",
            "routes",
            "payments",
            "status",
        )
        read_only_fields = ("id", "created", "status")


class HyperlinkedDepositSerializer(DepositSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-deposit-detail")

    class Meta:
        model = DepositSerializer.Meta.model
        fields = ("url",) + DepositSerializer.Meta.fields
        read_only_fields = DepositSerializer.Meta.read_only_fields


class DepositRouteSerializer(NestedHyperlinkedModelSerializer, PaymentRouteSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="deposit-routes-detail",
        parent_lookup_kwargs={
            "deposit_pk": "deposit_id",
        },
    )
    deposit = serializers.HyperlinkedRelatedField(view_name="user-deposit-detail", read_only=True)

    def _get_deposit(self):
        view = self.context["view"]
        return Deposit.objects.filter(pk=view.kwargs["deposit_pk"]).first()

    def validate(self, data):
        network = data["network"]
        deposit = self._get_deposit()

        if not network.supports_token(deposit.currency.subclassed):
            raise serializers.ValidationError(
                f"Can not make {deposit.currency.name} deposits on {network.name}"
            )

        for route in network.routes.filter(deposit=deposit).select_subclasses():
            if route.is_open:
                raise serializers.ValidationError(
                    f"Already has valid route for {network} deposits"
                )

        return data

    def create(self, validated_data):
        network = validated_data["network"]
        deposit = self._get_deposit()
        try:
            route_type = PaymentRoute.find_route_model(network)
            return route_type.make(deposit=deposit)
        except RoutingError:
            raise serializers.ValidationError(f"Failed to get {network} payment route")

    class Meta:
        model = PaymentRoute
        fields = ("url", "deposit", "network") + PaymentRouteSerializer.Meta.fields
        read_only_fields = ("url", "deposit") + PaymentRouteSerializer.Meta.read_only_fields


class PaymentOrderSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    amount = TokenValueField()

    class Meta:
        model = PaymentOrder
        fields = ("token", "amount", "reference")


class PaymentConfirmationSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="payment.currency")
    amount = TokenValueField(source="payment.amount")
    route = serializers.SerializerMethodField()

    def get_route(self, obj):
        route = PaymentRoute.objects.get_subclass(id=obj.payment.route_id)
        serializer_class = PaymentRouteSerializer.get_serializer_class(route)
        return serializer_class(route, context=self.context).data

    class Meta:
        model = PaymentConfirmation
        fields = read_only_fields = ("created", "token", "amount", "route")


__all__ = [
    "PaymentRouteSerializer",
    "InternalPaymentRouteSerializer",
    "PaymentSerializer",
    "InternalPaymentSerializer",
    "DepositSerializer",
    "HyperlinkedDepositSerializer",
    "DepositRouteSerializer",
    "PaymentOrderSerializer",
    "PaymentConfirmationSerializer",
]
