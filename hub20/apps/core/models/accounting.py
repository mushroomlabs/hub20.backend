import logging
from typing import Optional

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.db.models.query import QuerySet
from model_utils.models import TimeStampedModel

from .base import BaseModel
from .networks import PaymentNetwork
from .tokens import BaseToken, TokenAmount, TokenAmountField, TokenValueModel

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

    def with_funds(self, token_amount: TokenAmount):
        return self.grouped_by_token_balances().filter(
            balance__gte=token_amount.amount, token_id=token_amount.currency.id
        )


class Book(BaseModel):
    token = models.ForeignKey(BaseToken, on_delete=models.PROTECT, related_name="books")


class BookEntry(BaseModel, TimeStampedModel, TokenValueModel):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="entries")
    reference_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    reference_id = models.UUIDField()
    reference = GenericForeignKey("reference_type", "reference_id")

    def clean(self):
        if self.book.token != self.currency:
            raise ValidationError(
                f"Can not add a {self.currency} entry to a {self.book.token} book"
            )

    class Meta:
        abstract = True
        ordering = ("created",)
        unique_together = ("book", "reference_type", "reference_id")


class Credit(BookEntry):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="credits")


class Debit(BookEntry):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="debits")


class DoubleEntryAccountModel(BaseModel):
    book_relation_attr: Optional[str] = None
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

    def get_book(self, token: BaseToken) -> Book:
        book, _ = self.books.get_or_create(token=token)
        return book

    def get_balance_token_amount(self, token: BaseToken) -> Optional[TokenAmount]:
        balance = self.get_balance(token=token)
        return balance and TokenAmount(currency=token, amount=balance.balance)

    def get_balance(self, token: BaseToken) -> Optional[BaseToken]:
        return self.get_balances().filter(id=token.id).first()

    def get_balances(self) -> QuerySet:
        total_sum = Coalesce(Sum("amount"), 0, output_field=TokenAmountField())
        credit_qs = self.credits.values(token=F("book__token")).annotate(total_credit=total_sum)
        debit_qs = self.debits.values(token=F("book__token")).annotate(total_debit=total_sum)

        credit_sqs = credit_qs.filter(token=OuterRef("pk"))
        debit_sqs = debit_qs.filter(token=OuterRef("pk"))

        annotated_qs = BaseToken.objects.annotate(
            total_credit=Coalesce(
                Subquery(credit_sqs.values("total_credit")),
                0,
                output_field=TokenAmountField(),
            ),
            total_debit=Coalesce(
                Subquery(debit_sqs.values("total_debit")),
                0,
                output_field=TokenAmountField(),
            ),
        )
        return annotated_qs.annotate(balance=F("total_credit") - F("total_debit")).exclude(
            total_credit=0, total_debit=0
        )

    @classmethod
    def balance_sheet(cls):
        total_sum = Coalesce(Sum("amount"), 0, output_field=TokenAmountField())
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

        annotated_qs = BaseToken.objects.annotate(
            total_credit=Coalesce(
                Subquery(credit_sqs.values("total_credit")),
                0,
                output_field=TokenAmountField(),
            ),
            total_debit=Coalesce(
                Subquery(debit_sqs.values("total_debit")),
                0,
                output_field=TokenAmountField(),
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


class PaymentNetworkBook(Book):
    network = models.ForeignKey(PaymentNetwork, on_delete=models.CASCADE, related_name="books")


class UserBook(Book):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="books"
    )


class PaymentNetworkAccount(DoubleEntryAccountModel):
    book_relation_attr = "book__paymentnetworkbook__network__account"

    network = models.OneToOneField(
        PaymentNetwork, on_delete=models.CASCADE, related_name="account"
    )

    @property
    def books(self):
        return self.network.books

    @classmethod
    def make(cls, network):
        account, _ = cls.objects.get_or_create(network=network)
        return account


class UserAccount(DoubleEntryAccountModel):
    book_relation_attr = "book__userbook__user__account"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account"
    )

    @property
    def books(self):
        return self.user.books


__all__ = [
    "Book",
    "BookEntry",
    "Credit",
    "Debit",
    "PaymentNetworkAccount",
    "UserAccount",
]
