from typing import Dict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework_nested.relations import NestedHyperlinkedIdentityField
from rest_framework_nested.serializers import NestedHyperlinkedModelSerializer

from ..exceptions import RoutingError
from ..models import (
    Checkout,
    Deposit,
    InternalPayment,
    InternalPaymentRoute,
    Payment,
    PaymentConfirmation,
    PaymentNetwork,
    PaymentOrder,
    PaymentRoute,
    Store,
)
from .tokens import HyperlinkedRelatedTokenField, TokenSerializer, TokenValueField

PAYMENT_ROUTE_TYPES = PaymentRoute.__subclasses__()
PAYMENT_ROUTE_CHOICES = (c.NETWORK for c in PAYMENT_ROUTE_TYPES)
DEPOSIT_ROUTE_CHOICES = (c.NETWORK for c in PAYMENT_ROUTE_TYPES if c.NETWORK != "internal")


class PaymentRouteNetworkSelectorField(serializers.SlugRelatedField):
    def get_queryset(self):
        return PaymentNetwork.objects.all().select_subclasses()


class PaymentRouteSerializer(serializers.ModelSerializer):
    network = PaymentRouteNetworkSelectorField(slug_field="type")

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

    @staticmethod
    def get_route_model(network: PaymentNetwork):
        """
        Selects the model (subclass) of PaymentRoute model to use
        """
        return {m.NETWORK: m for m in PaymentRoute.__subclasses__()}[network]

    @staticmethod
    def get_serializer_class(route):
        """
        Finds which derived serializer to use for the route, based on the
        model in `Meta`
        """
        return {c.Meta.model: c for c in PaymentRouteSerializer.__subclasses__()}.get(
            type(route), PaymentRouteSerializer
        )


class InternalPaymentRouteSerializer(PaymentRouteSerializer):
    class Meta:
        model = InternalPaymentRoute
        fields = read_only_fields = ("recipient",)


class PaymentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField()
    url = serializers.HyperlinkedIdentityField(view_name="payments-detail")
    currency = TokenSerializer()
    confirmed = serializers.BooleanField(source="is_confirmed", read_only=True)

    @staticmethod
    def get_serializer_class(payment):
        """
        Finds which derived serializer to use for the payment, based on the
        model in `Meta`
        """
        return {c.Meta.model: c for c in PaymentSerializer.__subclasses__()}.get(
            type(payment), PaymentSerializer
        )

    class Meta:
        model = Payment
        fields = read_only_fields = (
            "id",
            "url",
            "created",
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
            return self.Meta.model.objects.create(
                user=request.user, session_key=request.session.session_key, **validated_data
            )

    def get_routes(self, obj):
        def get_route_serializer(route):
            serializer_class = PaymentRouteSerializer.get_serializer_class(route)
            return serializer_class(route, context=self.context)

        return [get_route_serializer(route).data for route in obj.routes.select_subclasses()]

    def get_payments(self, obj):
        def get_payment_serializer(payment):
            serializer_class = PaymentSerializer.get_serializer_class(payment)
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
    network = PaymentRouteNetworkSelectorField(slug_field="type")

    def _get_deposit(self):
        view = self.context["view"]
        return Deposit.objects.filter(pk=view.kwargs["deposit_pk"]).first()

    def validate(self, data):
        network = data["network"]
        deposit = self._get_deposit()
        route_type = PaymentRouteSerializer.get_route_model(network)

        if route_type.objects.filter(deposit=deposit).available().exists():
            raise serializers.ValidationError(f"Already has valid route for {network} deposits")

        if not deposit.network.supports_token(deposit.currency):
            raise serializers.ValidationError(
                f"Can not make {network} deposits with {deposit.currency.name}"
            )

        return data

    def create(self, validated_data):
        network = validated_data["network"]
        route_type = PaymentRouteSerializer.get_route_model(network)
        deposit = self._get_deposit()
        try:
            return route_type.make(deposit)
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


class CheckoutSerializer(serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    token = HyperlinkedRelatedTokenField(source="invoice.currency", write_only=True)
    amount = TokenValueField(source="invoice.amount", write_only=True)
    reference = serializers.CharField(source="invoice.reference", write_only=True, allow_null=True)
    invoice = PaymentOrderSerializer(source="order", read_only=True)

    routes = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    def get_routes(self, obj):
        def get_route_serializer(route):
            serializer_class = PaymentRouteSerializer.get_serializer_class(route)
            return serializer_class(route, context=self.context)

        return [get_route_serializer(route).data for route in obj.order.routes.select_subclasses()]

    def get_payments(self, obj):
        def get_payment_serializer(payment):
            serializer_class = PaymentSerializer.get_serializer_class(payment)
            return serializer_class(payment, context=self.context)

        return [get_payment_serializer(payment).data for payment in obj.order.payments]

    def validate(self, data):
        order = data["invoice"]
        store = data["store"]
        currency = order["currency"]
        if currency not in store.accepted_currencies.all():
            raise serializers.ValidationError(f"{currency.name} is not accepted at {store.name}")

        return data

    def create(self, validated_data):
        request = self.context.get("request")
        store = validated_data.pop("store")
        order_data = validated_data.pop("invoice")

        with transaction.atomic():
            order = PaymentOrder.objects.create(
                user=store.owner,
                session_key=request.session.session_key,
                **order_data,
            )
            return Checkout.objects.create(
                store=store,
                order=order,
            )

    class Meta:
        model = Checkout
        fields = (
            "id",
            "created",
            "expires_on",
            "store",
            "invoice",
            "payments",
            "routes",
            "voucher",
            "token",
            "amount",
            "reference",
        )
        read_only_fields = (
            "id",
            "created",
            "expires_on",
            "invoice",
            "voucher",
        )


class HttpCheckoutSerializer(CheckoutSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="checkout-detail")

    class Meta:
        model = Checkout
        fields = ("url",) + CheckoutSerializer.Meta.fields
        read_only_fields = CheckoutSerializer.Meta.read_only_fields


class CheckoutRouteSerializer(NestedHyperlinkedModelSerializer, PaymentRouteSerializer):
    url = NestedHyperlinkedIdentityField(
        view_name="checkout-routes-detail",
        parent_lookup_kwargs={
            "checkout_pk": "deposit__paymentorder__checkout__id",
        },
    )
    checkout = serializers.HyperlinkedRelatedField(
        source="deposit.checkout", view_name="checkout-detail", read_only=True
    )
    network = serializers.ChoiceField(choices=list(PAYMENT_ROUTE_CHOICES))

    def _get_checkout(self):
        view = self.context["view"]
        return Checkout.objects.filter(pk=view.kwargs["checkout_pk"]).first()

    def validate(self, data):
        network = data["network"]
        route_type = PaymentRouteSerializer.get_route_model(network)

        checkout = self._get_checkout()

        if checkout.expires_on <= timezone.now():
            raise serializers.ValidationError("Checkout is already expired")

        checkout_q = Q(deposit__paymentorder__checkout=checkout)
        if route_type.objects.filter(checkout_q).available().exists():
            raise serializers.ValidationError(f"Already has valid route for {network} payments")

        if not route_type.is_usable_for_token(checkout.order.currency):
            raise serializers.ValidationError(
                f"Can not make {network} payments with {checkout.order.currency.name}"
            )

        return data

    def create(self, validated_data):
        network = validated_data["network"]
        route_type = PaymentRouteSerializer.get_route_model(network)
        checkout = self._get_checkout()
        try:
            return route_type.make(checkout.order)
        except RoutingError:
            raise serializers.ValidationError(f"Failed to get {network} payment route")

    class Meta:
        model = PaymentRoute
        fields = ("url", "checkout", "network") + PaymentRouteSerializer.Meta.fields
        read_only_fields = ("url", "checkout") + PaymentRouteSerializer.Meta.read_only_fields


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
    "CheckoutSerializer",
    "HttpCheckoutSerializer",
    "CheckoutRouteSerializer",
]
