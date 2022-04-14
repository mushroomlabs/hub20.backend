from typing import Dict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.reverse import reverse
from rest_framework_nested.relations import NestedHyperlinkedIdentityField
from rest_framework_nested.serializers import NestedHyperlinkedModelSerializer

from hub20.apps.blockchain.serializers import EthereumAddressField, HexadecimalField
from hub20.apps.ethereum_money.models import EthereumToken, EthereumTokenAmount
from hub20.apps.ethereum_money.serializers import (
    EthereumTokenSerializer,
    HyperlinkedEthereumTokenSerializer,
    HyperlinkedRelatedTokenField,
    HyperlinkedTokenIdentityField,
    HyperlinkedTokenMixin,
    TokenValueField,
)

from . import models
from .exceptions import RoutingError

User = get_user_model()

PAYMENT_ROUTE_TYPES = models.PaymentRoute.__subclasses__()


PAYMENT_ROUTE_CHOICES = (c.NETWORK for c in PAYMENT_ROUTE_TYPES)
DEPOSIT_ROUTE_CHOICES = (c.NETWORK for c in PAYMENT_ROUTE_TYPES if c.NETWORK != "internal")


class UserRelatedField(serializers.SlugRelatedField):
    queryset = User.objects.filter(is_active=True)

    def __init__(self, *args, **kw):
        kw.setdefault("slug_field", "username")
        super().__init__(*args, **kw)


class StoreAcceptedTokenList(serializers.HyperlinkedRelatedField):
    view_name = "user-tokenlist-detail"

    def get_queryset(self):
        request = self.context.get("request")

        return request.user.token_lists.all()


class UserTokenSelectorField(HyperlinkedRelatedTokenField, HyperlinkedTokenMixin):
    def get_attribute(self, instance):
        return instance


class HyperlinkedBalanceIdentityField(serializers.HyperlinkedIdentityField):
    def __init__(self, *args, **kw):
        kw.setdefault("view_name", "balance-detail")
        super().__init__(*args, **kw)

    def get_url(self, obj, view_name, request, format):
        url_kwargs = {"chain_id": obj.chain_id, "address": obj.address}
        return reverse(view_name, kwargs=url_kwargs, request=request, format=format)


class UserSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="users-detail", lookup_field="username")

    class Meta:
        model = User
        fields = read_only_fields = ("url", "username", "first_name", "last_name", "email")


class TokenBalanceSerializer(EthereumTokenSerializer):
    token = HyperlinkedTokenIdentityField(view_name="token-detail")
    amount = TokenValueField(read_only=True, source="balance")

    class Meta:
        model = EthereumTokenSerializer.Meta.model
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


class TokenRouteDescriptorSerializer(HyperlinkedTokenMixin, EthereumTokenSerializer):
    url = HyperlinkedTokenIdentityField(view_name="token-routes")
    token = HyperlinkedTokenIdentityField(view_name="token-detail")
    blockchain = serializers.HyperlinkedRelatedField(
        view_name="blockchain:chain-detail", source="chain_id", read_only=True
    )
    networks = serializers.SerializerMethodField()

    def get_networks(self, obj):
        return {"raiden": hasattr(obj, "tokennetwork")}

    class Meta:
        model = EthereumTokenSerializer.Meta.model
        fields = ("url", "token", "blockchain", "networks")
        read_only_fields = ("url", "token", "blockchain", "networks")


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
        transfer_amount = EthereumTokenAmount(currency=currency, amount=data["amount"])
        user_balance_amount = request.user.account.get_balance_token_amount(currency)

        if not user_balance_amount:
            raise serializers.ValidationError("No balance available", code="invalid")

        if user_balance_amount < transfer_amount:
            raise serializers.ValidationError("Insufficient balance", code="insufficient")

        return data

    def create(self, validated_data):
        request = self.context["request"]

        return self.Meta.model.objects.create(sender=request.user, **validated_data)


class InternalTransferSerializer(TransferSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-transfer-detail")
    recipient = UserRelatedField(source="receiver")

    def validate_recipient(self, value):
        request = self.context["request"]
        if value == request.user:
            raise serializers.ValidationError("You can not make a transfer to yourself")
        return value

    class Meta:
        model = models.InternalTransfer
        fields = (
            "url",
            "reference",
            "recipient",
            "amount",
            "token",
            "memo",
            "identifier",
            "status",
        )
        read_only_fields = ("reference", "status")


class WithdrawalSerializer(TransferSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-withdrawal-detail")
    address = EthereumAddressField()

    def validate_recipient(self, value):
        request = self.context["request"]
        if value == request.user:
            raise serializers.ValidationError("You can not make a transfer to yourself")
        return value

    class Meta:
        model = models.Withdrawal
        fields = (
            "url",
            "reference",
            "address",
            "payment_network",
            "amount",
            "token",
            "memo",
            "identifier",
            "status",
        )
        read_only_fields = ("reference", "status")


class TransferConfirmationSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="transfer.currency")
    target = serializers.CharField(source="transfer.target", read_only=True)
    amount = TokenValueField(source="transfer.amount")

    class Meta:
        model = models.TransferConfirmation
        fields = read_only_fields = ("created", "token", "amount", "target")


class PaymentRouteSerializer(serializers.ModelSerializer):
    network = serializers.SerializerMethodField()

    def get_network(self, obj):
        return obj.network

    class Meta:
        model = models.PaymentRoute
        fields = ("id", "identifier", "network", "is_expired", "is_open", "is_used")
        read_only_fields = ("id", "network", "identifier", "is_expired", "is_open", "is_used")

    @staticmethod
    def get_route_model(network: str):
        """
        Selects the model (subclass) of PaymentRoute model to use
        """
        return {m.NETWORK: m for m in models.PaymentRoute.__subclasses__()}[network]

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
        model = models.InternalPaymentRoute
        fields = read_only_fields = ("recipient",)


class BlockchainPaymentRouteSerializer(PaymentRouteSerializer):
    address = EthereumAddressField(source="account.address", read_only=True)
    expiration_block = serializers.IntegerField(source="expiration_block_number", read_only=True)

    class Meta:
        model = models.BlockchainPaymentRoute
        fields = PaymentRouteSerializer.Meta.fields + (
            "address",
            "expiration_block",
        )
        read_only_fields = PaymentRouteSerializer.Meta.read_only_fields + (
            "address",
            "expiration_block",
        )


class RaidenPaymentRouteSerializer(PaymentRouteSerializer):
    address = EthereumAddressField(source="raiden.address", read_only=True)

    class Meta:
        model = models.RaidenPaymentRoute
        fields = PaymentRouteSerializer.Meta.fields + (
            "address",
            "expiration_time",
        )
        read_only_fields = PaymentRouteSerializer.Meta.read_only_fields + (
            "address",
            "expiration_time",
        )


class PaymentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField()
    url = serializers.HyperlinkedIdentityField(view_name="payments-detail")
    currency = EthereumTokenSerializer()
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
        model = models.Payment
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
        model = models.InternalPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "user", "memo")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "user",
            "memo",
        )


class BlockchainPaymentSerializer(PaymentSerializer):
    transaction = HexadecimalField(source="transaction.hash", read_only=True)
    block = serializers.IntegerField(source="transaction.block.number", read_only=True)

    class Meta:
        model = models.BlockchainPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "transaction", "block")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "transaction",
            "block",
        )


class RaidenPaymentSerializer(PaymentSerializer):
    raiden = serializers.CharField(source="payment.channel.raiden.address")

    class Meta:
        model = models.RaidenPayment
        fields = PaymentSerializer.Meta.fields + ("identifier", "raiden")
        read_only_fields = PaymentSerializer.Meta.read_only_fields + (
            "identifier",
            "raiden",
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
        model = models.Deposit
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
    network = serializers.ChoiceField(choices=list(DEPOSIT_ROUTE_CHOICES))

    def _get_deposit(self):
        view = self.context["view"]
        return models.Deposit.objects.filter(pk=view.kwargs["deposit_pk"]).first()

    def validate(self, data):
        network = data["network"]
        route_type = PaymentRouteSerializer.get_route_model(network)

        deposit = self._get_deposit()

        if route_type.objects.filter(deposit=deposit).available().exists():
            raise serializers.ValidationError(f"Already has valid route for {network} deposits")

        if not route_type.is_usable_for_token(deposit.currency):
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
        model = models.PaymentRoute
        fields = ("url", "deposit", "network") + PaymentRouteSerializer.Meta.fields
        read_only_fields = ("url", "deposit") + PaymentRouteSerializer.Meta.read_only_fields


class PaymentOrderSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    amount = TokenValueField()

    class Meta:
        model = models.PaymentOrder
        fields = ("token", "amount", "reference")


class PaymentConfirmationSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="payment.currency")
    amount = TokenValueField(source="payment.amount")
    route = serializers.SerializerMethodField()

    def get_route(self, obj):
        route = models.PaymentRoute.objects.get_subclass(id=obj.payment.route_id)
        serializer_class = PaymentRouteSerializer.get_serializer_class(route)
        return serializer_class(route, context=self.context).data

    class Meta:
        model = models.PaymentConfirmation
        fields = read_only_fields = ("created", "token", "amount", "route")


class CheckoutSerializer(serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(queryset=models.Store.objects.all())
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
            order = models.PaymentOrder.objects.create(
                user=store.owner,
                session_key=request.session.session_key,
                **order_data,
            )
            return models.Checkout.objects.create(
                store=store,
                order=order,
            )

    class Meta:
        model = models.Checkout
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
        model = models.Checkout
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
        return models.Checkout.objects.filter(pk=view.kwargs["checkout_pk"]).first()

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
        model = models.PaymentRoute
        fields = ("url", "checkout", "network") + PaymentRouteSerializer.Meta.fields
        read_only_fields = ("url", "checkout") + PaymentRouteSerializer.Meta.read_only_fields


class StoreSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="store-detail")
    site_url = serializers.URLField(source="url")
    public_key = serializers.CharField(source="rsa.public_key_pem", read_only=True)

    class Meta:
        model = models.Store
        fields = ("id", "url", "name", "site_url", "public_key")
        read_only_fields = ("id", "public_key")


class StoreViewerSerializer(StoreSerializer):
    accepted_currencies = HyperlinkedEthereumTokenSerializer(many=True)

    class Meta:
        model = models.Store
        fields = read_only_fields = (
            "id",
            "url",
            "name",
            "site_url",
            "public_key",
            "accepted_currencies",
        )


class StoreEditorSerializer(StoreSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="user-store-detail")
    accepted_token_list = StoreAcceptedTokenList()
    checkout_webhook_url = serializers.URLField(allow_null=True, required=False)

    def create(self, validated_data):
        request = self.context.get("request")
        return models.Store.objects.create(owner=request.user, **validated_data)

    class Meta:
        model = models.Store
        fields = StoreSerializer.Meta.fields + (
            "accepted_token_list",
            "checkout_webhook_url",
        )
        read_only_fields = StoreSerializer.Meta.read_only_fields


class UserTokenSerializer(EthereumTokenSerializer):
    url = HyperlinkedTokenIdentityField(view_name="user-token-detail")
    token = HyperlinkedTokenIdentityField(view_name="token-detail", read_only=True)
    address = EthereumAddressField(read_only=True)
    chain_id = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = EthereumTokenSerializer.Meta.model
        fields = ("url", "token") + EthereumTokenSerializer.Meta.fields
        read_only_fields = ("url", "token") + EthereumTokenSerializer.Meta.fields


class UserTokenCreatorSerializer(serializers.ModelSerializer):
    url = HyperlinkedTokenIdentityField(view_name="user-token-detail")
    token = UserTokenSelectorField(view_name="token-detail")

    def validate(self, data):
        token = data["token"]
        if not EthereumToken.tradeable.filter(id=token.id).exists():
            raise serializers.ValidationError(
                f"Token {token.symbol} on chain #{token.chain_id} is not listed for trade"
            )
        return data

    def create(self, validated_data):
        request = self.context["request"]
        token = validated_data["token"]
        native_token = EthereumToken.make_native(token.chain)
        request.user.preferences.tokens.add(token)
        request.user.preferences.tokens.add(native_token)
        return token

    class Meta:
        model = EthereumTokenSerializer.Meta.model
        fields = ("url", "token") + EthereumTokenSerializer.Meta.fields
        read_only_fields = ("url",) + EthereumTokenSerializer.Meta.fields


class BookEntrySerializer(serializers.ModelSerializer):
    amount = serializers.CharField(source="as_token_amount")
    reference_type = serializers.CharField(source="reference_type.model")
    reference = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    def get_type(self, obj):
        return obj.__class__.__name__.lower()

    def get_summary(self, obj):
        return {
            models.Transfer: "transfer",
            models.TransferConfirmation: "transfer sent",
            models.PaymentConfirmation: "payment received",
        }.get(type(obj.reference))

    def get_reference(self, obj):
        params = {
            models.TransferConfirmation: lambda: {
                "viewname": "transfer-detail",
                "kwargs": {"pk": obj.reference.transfer.pk},
            },
            models.PaymentConfirmation: lambda: {
                "viewname": "payments-detail",
                "kwargs": {"pk": obj.reference.payment.pk},
            },
            models.Transfer: lambda: {
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
        model = models.Credit
        fields = read_only_fields = BookEntrySerializer.Meta.fields


class DebitSerializer(BookEntrySerializer):
    class Meta:
        model = models.Debit
        fields = read_only_fields = BookEntrySerializer.Meta.fields


class UserPreferencesSerializer(serializers.ModelSerializer):
    tokens = HyperlinkedRelatedTokenField(
        view_name="token-detail",
        queryset=EthereumToken.tradeable.all(),
        many=True,
    )

    class Meta:
        model = models.UserPreferences
        fields = ("tokens",)


class AccountingBookSerializer(serializers.Serializer):
    token = HyperlinkedTokenIdentityField(view_name="token-detail", source="*")
    total_credit = TokenValueField(read_only=True)
    total_debit = TokenValueField(read_only=True)
    balance = TokenValueField(read_only=True)
