from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework_nested.relations import NestedHyperlinkedIdentityField
from rest_framework_nested.serializers import NestedHyperlinkedModelSerializer

from ..exceptions import RoutingError
from ..models import Checkout, PaymentOrder, PaymentRoute, Store
from .payments import PaymentOrderSerializer, PaymentRouteSerializer, PaymentSerializer
from .tokens import HyperlinkedRelatedTokenField, HyperlinkedTokenSerializer, TokenValueField


class StoreAcceptedTokenListSelectorField(serializers.HyperlinkedRelatedField):
    view_name = "user-tokenlist-detail"

    def get_queryset(self):
        request = self.context.get("request")
        return request.user.token_lists.all()


class StoreSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="store-detail")
    site_url = serializers.URLField(source="url")
    public_key = serializers.CharField(source="rsa.public_key_pem", read_only=True)

    class Meta:
        model = Store
        fields = ("id", "url", "name", "site_url", "public_key")
        read_only_fields = ("id", "public_key")


class StoreEditorSerializer(StoreSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-store-detail")
    accepted_token_list = StoreAcceptedTokenListSelectorField()
    checkout_webhook_url = serializers.URLField(allow_null=True, required=False)

    def create(self, validated_data):
        request = self.context.get("request")
        return Store.objects.create(owner=request.user, **validated_data)

    class Meta:
        model = Store
        fields = StoreSerializer.Meta.fields + (
            "accepted_token_list",
            "checkout_webhook_url",
        )
        read_only_fields = StoreSerializer.Meta.read_only_fields


class StoreViewerSerializer(StoreSerializer):
    accepted_currencies = HyperlinkedTokenSerializer(many=True)

    class Meta:
        model = Store
        fields = read_only_fields = (
            "id",
            "url",
            "name",
            "site_url",
            "public_key",
            "accepted_currencies",
        )


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

    def _get_checkout(self):
        view = self.context["view"]
        return Checkout.objects.filter(pk=view.kwargs["checkout_pk"]).first()

    def validate(self, data):
        checkout = self._get_checkout()

        if checkout.expires_on <= timezone.now():
            raise serializers.ValidationError("Checkout is already expired")

        network = data["network"]
        if not network.supports_token(checkout.order.currency.subclassed):
            raise serializers.ValidationError(
                f"Can not make {network.type} payments with {checkout.order.currency.name}"
            )

        checkout_q = Q(deposit__paymentorder__checkout=checkout)
        for route in network.routes.filter(checkout_q).select_subclasses():
            if route.is_open:
                raise serializers.ValidationError(
                    f"Already has open route for {network.name} payments"
                )

        return data

    def create(self, validated_data):
        network = validated_data["network"]
        checkout = self._get_checkout()
        try:
            route_type = PaymentRoute.find_route_model(network)
            return route_type.make(deposit=checkout.order)
        except RoutingError:
            raise serializers.ValidationError(f"Failed to get {network} payment route")

    class Meta:
        model = PaymentRoute
        fields = ("url", "checkout", "network") + PaymentRouteSerializer.Meta.fields
        read_only_fields = ("url", "checkout") + PaymentRouteSerializer.Meta.read_only_fields


__all__ = [
    "StoreSerializer",
    "StoreEditorSerializer",
    "StoreViewerSerializer",
    "CheckoutSerializer",
    "HttpCheckoutSerializer",
    "CheckoutRouteSerializer",
]
