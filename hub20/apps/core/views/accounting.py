from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from hub20.apps.core.models.tokens import BaseToken

from .. import models, serializers


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
        return self.request.user.account.get_balances()


class TokenBalanceView(generics.RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.HyperlinkedTokenBalanceSerializer

    def get_object(self) -> BaseToken:
        token = get_object_or_404(BaseToken, id=self.kwargs["pk"])
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
