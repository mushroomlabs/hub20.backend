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


class AccountingReportView(APIView):
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
