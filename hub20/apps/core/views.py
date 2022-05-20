from django.contrib.auth import get_user_model
from django.db.models import BooleanField, Case, Value, When
from django.db.models.query import QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.mixins import (
    CreateModelMixin,
    DestroyModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from hub20.apps.blockchain.client import make_web3
from hub20.apps.core.serializers import AddressSerializerField
from hub20.apps.ethereum_money.client import get_estimate_fee
from hub20.apps.ethereum_money.models import Token
from hub20.apps.ethereum_money.serializers import HyperlinkedRelatedTokenField, TokenValueField
from hub20.apps.ethereum_money.views import BaseTokenViewSet, TokenViewSet

from . import models, serializers
from .filters import DepositFilter, UserFilter
from .permissions import IsStoreOwner

User = get_user_model()


class AccountCreditEntryList(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.CreditSerializer

    def get_queryset(self) -> QuerySet:
        return models.Credit.objects.filter(book__account__user=self.request.user)


class AccountDebitEntryList(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.DebitSerializer

    def get_queryset(self) -> QuerySet:
        return self.request.user.account.debits.all()


class DepositViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.HyperlinkedDepositSerializer
    filterset_class = DepositFilter
    filter_backends = (
        OrderingFilter,
        DjangoFilterBackend,
    )
    ordering = "-created"

    def get_queryset(self) -> QuerySet:
        return self.request.user.deposit_set.all()

    def get_object(self) -> models.Deposit:
        return get_object_or_404(models.Deposit, pk=self.kwargs.get("pk"), user=self.request.user)


class DepositRoutesViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    """
    Manages routes related to a deposit
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.DepositRouteSerializer
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self, *args, **kw):
        deposit_id = self.kwargs["deposit_pk"]
        return models.PaymentRoute.objects.filter(deposit_id=deposit_id).select_subclasses()


class TokenBrowserViewSet(TokenViewSet):
    def get_serializer_class(self):
        if self.action == "balance":
            return serializers.HyperlinkedTokenBalanceSerializer
        elif self.action == "routes":
            return serializers.TokenRouteDescriptorSerializer

        return super().get_serializer_class()

    @action(detail=True)
    def transfer_cost(self, request, **kwargs):
        """
        Returns estimated cost in Wei (estimated gas * gas price) to execute a transfer

        Returns 404 if not connected to the blockchain or if token not in database
        """
        token = self.get_object()
        try:
            w3 = make_web3(provider=token.chain.provider)
            transfer_cost = get_estimate_fee(w3=w3, token=token)
            return Response(transfer_cost.as_wei)
        except AttributeError:
            raise Http404
        except TypeError:
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @action(detail=True, permission_classes=(IsAuthenticated,))
    def balance(self, request, **kwargs):
        """
        Returns user balance for that token
        """
        try:
            token = self.get_object()
            balance = self.request.user.account.get_balance(token)
            serializer = self.get_serializer(instance=balance)
            return Response(serializer.data)
        except AttributeError:
            raise Http404

    @action(detail=True)
    def routes(self, request, **kwargs):
        """
        Returns list of all routes that can be used for deposits/withdrawals in the hub
        """
        token = self.get_object()
        serializer = self.get_serializer(instance=token)
        return Response(serializer.data)


class TransferViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.InternalTransferSerializer

    def get_queryset(self) -> QuerySet:
        return models.InternalTransfer.objects.filter(sender=self.request.user)


class WithdrawalViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.WithdrawalSerializer

    def get_queryset(self) -> QuerySet:
        return self.request.user.transfers_sent.filter(
            internaltransfer__isnull=True
        ).select_subclasses()


class TokenBalanceListView(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.HyperlinkedTokenBalanceSerializer
    filter_backends = (OrderingFilter,)
    ordering = ("chain_id", "-is_native", "symbol")

    def get_queryset(self) -> QuerySet:
        return self.request.user.account.get_balances().annotate(
            is_native=Case(
                When(address=Token.NULL_ADDRESS, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )


class TokenBalanceView(generics.RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.HyperlinkedTokenBalanceSerializer

    def get_object(self) -> Token:
        token = get_object_or_404(
            Token, chain_id=self.kwargs["chain_id"], address=self.kwargs["address"]
        )
        return self.request.user.account.get_balance(token)


class CheckoutViewSet(GenericViewSet, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (AllowAny,)
    serializer_class = serializers.HttpCheckoutSerializer
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self):
        return models.Checkout.objects.all()

    def get_object(self):
        return get_object_or_404(models.Checkout, id=self.kwargs["pk"])


class CheckoutRoutesViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    """
    Manages routes related to a checkout
    """

    permission_classes = (AllowAny,)
    serializer_class = serializers.CheckoutRouteSerializer
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self, *args, **kw):
        checkout_id = self.kwargs["checkout_pk"]
        return models.PaymentRoute.objects.filter(
            deposit__paymentorder__checkout=checkout_id
        ).select_subclasses()


class PaymentViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self):
        return models.Payment.objects.all()

    def get_permissions(self):
        permission_class = IsAdminUser if self.action == "list" else AllowAny
        return (permission_class(),)

    def get_serializer_class(self):
        if self.action == "list":
            return serializers.PaymentSerializer

        payment = self.get_object()

        return {
            models.InternalPayment: serializers.InternalPaymentSerializer,
            models.BlockchainPayment: serializers.BlockchainPaymentSerializer,
            models.RaidenPayment: serializers.RaidenPaymentSerializer,
        }.get(type(payment), serializers.PaymentSerializer)

    def get_object(self):
        try:
            return models.Payment.objects.get_subclass(id=self.kwargs["pk"])
        except (models.Payment.DoesNotExist, KeyError):
            return None


class StoreViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (AllowAny,)
    serializer_class = serializers.StoreViewerSerializer
    queryset = models.Store.objects.all()

    def get_object(self, *args, **kw):
        return get_object_or_404(models.Store, id=self.kwargs["pk"])


class UserStoreViewSet(ModelViewSet):
    permission_classes = (IsStoreOwner,)
    serializer_class = serializers.StoreEditorSerializer
    filter_backends = (OrderingFilter,)
    ordering = "id"

    def get_queryset(self) -> QuerySet:
        try:
            return self.request.user.store_set.all()
        except AttributeError:
            return models.Store.objects.none()

    def get_object(self, *args, **kw):
        store = get_object_or_404(models.Store, id=self.kwargs["pk"])
        self.check_object_permissions(self.request, store)
        return store


class UserTokenViewSet(BaseTokenViewSet, CreateModelMixin, DestroyModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.UserTokenSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return serializers.UserTokenCreatorSerializer

        return self.serializer_class

    def get_queryset(self) -> QuerySet:
        qs = super().get_queryset()
        return qs.filter(userpreferences__user=self.request.user)

    def destroy(self, *args, **kw):
        token = self.get_object()
        self.request.user.preferences.tokens.remove(token)
        return Response(status.HTTP_204_NO_CONTENT)


class UserPreferencesView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.UserPreferencesSerializer

    def get_object(self) -> QuerySet:
        return self.request.user.preferences


class UserViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.UserSerializer
    filterset_class = UserFilter
    filter_backends = (
        OrderingFilter,
        DjangoFilterBackend,
    )
    lookup_field = "username"
    ordering = "username"

    def get_queryset(self) -> QuerySet:
        return User.objects.filter(is_active=True, is_superuser=False, is_staff=False)

    def get_object(self, *args, **kw):
        return get_object_or_404(
            User,
            is_active=True,
            is_superuser=False,
            is_staff=False,
            username=self.kwargs["username"],
        )


class StatusView(APIView):
    permission_classes = (IsAuthenticated,)


class AccountingReportView(StatusView):
    permission_classes = (IsAdminUser,)

    def _get_serialized_book(self, accounting_model_class):
        books = accounting_model_class.balance_sheet().exclude(total_credit=0, total_debit=0)
        return serializers.AccountingBookSerializer(
            books, many=True, context={"request": self.request}
        ).data

    def get(self, request, **kw):
        return Response(
            dict(
                payment_networks=self._get_serialized_book(models.PaymentNetworkAccount),
                user_accounts=self._get_serialized_book(models.UserAccount),
            )
        )


class WalletBalanceSerializer(serializers.ModelSerializer):
    token = HyperlinkedRelatedTokenField(source="currency")
    balance = TokenValueField(source="amount")
    block = serializers.IntegerField(source="block.number", read_only=True)

    class Meta:
        model = models.WalletBalanceRecord
        fields = read_only_fields = ("token", "balance", "block")


class WalletSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="wallet-detail", lookup_field="address")

    address = AddressSerializerField(read_only=True)
    balances = WalletBalanceSerializer(many=True, read_only=True)

    class Meta:
        model = models.Wallet
        fields = read_only_fields = ("url", "address", "balances")


class WalletViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAdminUser,)
    serializer_class = serializers.WalletSerializer
    lookup_url_kwarg = "address"
    lookup_field = "address"

    def get_queryset(self) -> QuerySet:
        return models.Wallet.objects.all()
