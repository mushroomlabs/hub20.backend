from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from hub20.apps.core.models.tokens import BaseToken

from .. import models, serializers
from .base import UserDataViewSet


class AccountCreditViewSet(UserDataViewSet):
    serializer_class = serializers.CreditSerializer

    def get_queryset(self) -> QuerySet:
        return self.request.user.account.credits.all()


class AccountDebitViewSet(UserDataViewSet):
    serializer_class = serializers.DebitSerializer

    def get_queryset(self) -> QuerySet:
        return self.request.user.account.debits.all()


class TokenBalanceListViewSet(UserDataViewSet):
    serializer_class = serializers.HyperlinkedTokenBalanceSerializer
    filter_backends = (OrderingFilter,)
    ordering = ("symbol",)

    def get_queryset(self) -> QuerySet:
        return self.request.user.account.get_balances()

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


__all__ = [
    "AccountCreditViewSet",
    "AccountDebitViewSet",
    "TokenBalanceListViewSet",
    "AccountingReportView",
]
