import logging
from typing import Optional

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.db.models.query import QuerySet
from model_utils.models import TimeStampedModel

from hub20.apps.ethereum_money.models import (
    EthereumToken,
    EthereumTokenAmount,
    EthereumTokenAmountField,
    EthereumTokenValueModel,
)

from ..choices import PAYMENT_NETWORKS

logger = logging.getLogger(__name__)


class DoubleEntryAccountModelQuerySet(models.QuerySet):
    def grouped_by_token_balances(self):
        credit = Coalesce(Sum("books__credits__amount"), 0, output_field=models.DecimalField())
        debit = Coalesce(Sum("books__debits__amount"), 0, output_field=models.DecimalField())

        return (
            self.exclude(books__token=None)
            .annotate(token_id=F("books__token"))
            .annotate(total_credit=credit, total_debit=debit)
            .annotate(balance=F("total_credit") - F("total_debit"))
        )

    def with_funds(self, token_amount: EthereumTokenAmount):
        return self.grouped_by_token_balances().filter(
            balance__gte=token_amount.amount, token_id=token_amount.currency.id
        )


class Book(models.Model):
    token = models.ForeignKey(EthereumToken, on_delete=models.PROTECT, related_name="books")
    owner_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    owner_id = models.PositiveIntegerField()
    owner = GenericForeignKey("owner_type", "owner_id")

    class Meta:
        unique_together = ("token", "owner_type", "owner_id")


class BookEntry(TimeStampedModel, EthereumTokenValueModel):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="entries")
    reference_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    reference_id = models.PositiveIntegerField()
    reference = GenericForeignKey("reference_type", "reference_id")

    def clean(self):
        if self.book.token != self.currency:
            raise ValidationError(
                f"Can not add a {self.currency} entry to a {self.book.token} book"
            )

    class Meta:
        abstract = True
        unique_together = ("book", "reference_type", "reference_id")


class Credit(BookEntry):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="credits")


class Debit(BookEntry):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="debits")


class DoubleEntryAccountModel(models.Model):
    book_relation_attr: Optional[str] = None
    token_balance_relation_attr: Optional[str] = None
    objects = DoubleEntryAccountModelQuerySet.as_manager()

    @property
    def debits(self):
        return Debit.objects.filter(**{self.book_relation_attr: self})

    @property
    def credits(self):
        return Credit.objects.filter(**{self.book_relation_attr: self})

    @property
    def balances(self):
        return self.get_balances()

    def get_book(self, token: EthereumToken) -> Book:
        book, _ = self.books.get_or_create(token=token)
        return book

    def get_balance_token_amount(self, token: EthereumToken) -> Optional[EthereumTokenAmount]:
        balance = self.get_balance(token=token)
        return balance and EthereumTokenAmount(currency=token, amount=balance.balance)

    def get_balance(self, token: EthereumToken) -> Optional[EthereumToken]:
        return self.get_balances().filter(id=token.id).first()

    def get_balances(self) -> QuerySet:
        total_sum = Coalesce(Sum("amount"), 0, output_field=EthereumTokenAmountField())
        credit_qs = self.credits.values(token=F("book__token")).annotate(total_credit=total_sum)
        debit_qs = self.debits.values(token=F("book__token")).annotate(total_debit=total_sum)

        credit_sqs = credit_qs.filter(token=OuterRef("pk"))
        debit_sqs = debit_qs.filter(token=OuterRef("pk"))

        annotated_qs = EthereumToken.objects.annotate(
            total_credit=Coalesce(
                Subquery(credit_sqs.values("total_credit")),
                0,
                output_field=EthereumTokenAmountField(),
            ),
            total_debit=Coalesce(
                Subquery(debit_sqs.values("total_debit")),
                0,
                output_field=EthereumTokenAmountField(),
            ),
        )
        return annotated_qs.annotate(balance=F("total_credit") - F("total_debit")).exclude(
            total_credit=0, total_debit=0
        )

    @classmethod
    def balance_sheet(cls):
        total_sum = Coalesce(Sum("amount"), 0, output_field=EthereumTokenAmountField())
        filter_q = {f"{cls.book_relation_attr}__isnull": False}
        credit_qs = (
            Credit.objects.filter(**filter_q)
            .values(token=F("book__token"))
            .annotate(total_credit=total_sum)
        )
        debit_qs = (
            Debit.objects.filter(**filter_q)
            .values(token=F("book__token"))
            .annotate(total_debit=total_sum)
        )

        credit_sqs = credit_qs.filter(token=OuterRef("pk"))
        debit_sqs = debit_qs.filter(token=OuterRef("pk"))

        annotated_qs = EthereumToken.objects.annotate(
            total_credit=Coalesce(
                Subquery(credit_sqs.values("total_credit")),
                0,
                output_field=EthereumTokenAmountField(),
            ),
            total_debit=Coalesce(
                Subquery(debit_sqs.values("total_debit")),
                0,
                output_field=EthereumTokenAmountField(),
            ),
        )
        return annotated_qs.annotate(balance=F("total_credit") - F("total_debit"))

    class Meta:
        abstract = True


##############################################################################
#
# The following diagram illustrates how the different accounts part of the
# system have their funds accounted for.
#
#
#      Blockchain Account               Raiden Network Acounts
#              +                           +
#              |                           |
#              |       +----------+        |
#              +------>+          +<-------+
#                      | Treasury |
#              +------>+          +<-------+
#              |       +----+-----+        |
#              |            ^              |
#              +            |              +
#             User        User            User
#
#

# Each type of payment network (blockchain, raiden) has its own
# account. We do not need to make separate accounts for each chain,
# because the chain information is managed by the relationship with
# the token. Transfers made to/from the networks should count as
# debits/credits to the treasury (and the credit/debit to the
# counterparty network)

#
# User funds are accounted in a similar manner. Transfers done by the user
# should be treated as a credit to the treasury, and payments related to
# payment orders should lead to a credit to the user.
#
# We should at the very least have the following equations being satisfied per
# token, else the site should be considered insolvent:
#
#        (I)   Assets = Ethereum Accounts + Raiden
#       (II)   Assets >= User Balances
#      (III) Treasury = Assets - User Balances
#
# All of these operations are now defined at the handlers.accounting module.
#
#############################################################################
class PaymentNetworkAccount(DoubleEntryAccountModel):

    book_relation_attr = "book__network"
    token_balance_relation_attr = "books__network"

    payment_network = models.CharField(max_length=100, choices=PAYMENT_NETWORKS, unique=True)

    books = GenericRelation(
        Book,
        content_type_field="owner_type",
        object_id_field="owner_id",
        related_query_name="network",
    )

    @classmethod
    def make(cls, network):
        account, _ = cls.objects.get_or_create(payment_network=network)
        return account


class UserAccount(DoubleEntryAccountModel):
    book_relation_attr = "book__account"
    token_balance_relation_attr = "books__account"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account"
    )
    books = GenericRelation(
        Book,
        content_type_field="owner_type",
        object_id_field="owner_id",
        related_query_name="account",
    )


__all__ = [
    "Book",
    "BookEntry",
    "Credit",
    "Debit",
    "PaymentNetworkAccount",
    "UserAccount",
]
