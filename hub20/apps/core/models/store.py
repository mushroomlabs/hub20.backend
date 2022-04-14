import datetime
import uuid
from typing import Optional

import jwt
from Crypto.PublicKey import RSA
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from model_utils.models import TimeStampedModel

from hub20.apps.ethereum_money.models import EthereumToken, UserTokenList

from ..settings import app_settings
from .payments import PaymentOrder


def calculate_checkout_expiration_time():
    return timezone.now() + datetime.timedelta(seconds=app_settings.Payment.checkout_lifetime)


class Store(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=300)
    url = models.URLField(help_text="URL for your store public site or information page")
    checkout_webhook_url = models.URLField(null=True, help_text="URL to receive checkout updates")
    accepted_token_list = models.ForeignKey(
        UserTokenList,
        null=True,
        help_text="The list of tokens that will be accepted for payment",
        on_delete=models.SET_NULL,
    )

    @property
    def accepted_currencies(self):
        if self.accepted_token_list:
            qs = self.accepted_token_list.tokens.all()
        else:
            qs = EthereumToken.tradeable.all()

        return qs.filter(chain__providers__is_active=True)

    def issue_jwt(self, **data):
        data.update(
            {
                "iat": datetime.datetime.utcnow(),
                "iss": str(self.id),
            }
        )

        private_key = self.rsa.private_key_pem.encode()
        return jwt.encode(data, private_key, algorithm="RS256")

    def __str__(self):
        return f"{self.name} ({self.url})"


class StoreRSAKeyPair(models.Model):
    DEFAULT_KEY_SIZE = 2048

    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name="rsa")
    public_key_pem = models.TextField()
    private_key_pem = models.TextField()

    @classmethod
    def generate(cls, store: Store, keysize: Optional[int] = None):
        bits = keysize or cls.DEFAULT_KEY_SIZE
        key = RSA.generate(bits)
        public_key_pem = key.publickey().export_key().decode()
        private_key_pem = key.export_key().decode()

        pair, _ = cls.objects.update_or_create(
            store=store,
            defaults={"public_key_pem": public_key_pem, "private_key_pem": private_key_pem},
        )
        return pair


class Checkout(TimeStampedModel):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    expires_on = models.DateTimeField(default=calculate_checkout_expiration_time)
    order = models.OneToOneField(PaymentOrder, related_name="checkout", on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.CASCADE)

    @property
    def voucher_data(self):
        return {
            "checkout_id": str(self.id),
            "reference": self.order.reference,
            "token": {
                "symbol": self.order.currency.symbol,
                "address": self.order.currency.address,
                "chain_id": self.order.currency.chain_id,
            },
            "payments": [
                {
                    "id": str(p.id),
                    "amount": str(p.amount),
                    "confirmed": p.is_confirmed,
                    "identifier": p.identifier,
                    "route": p.route.network,
                }
                for p in self.order.payments
            ],
            "total_amount": str(self.order.amount),
            "total_confirmed": str(self.order.total_confirmed),
            "is_paid": self.order.is_paid,
            "is_confirmed": self.order.is_confirmed,
        }

    @property
    def voucher(self):
        return self.store.issue_jwt(**self.voucher_data)

    def clean(self):
        if self.store.owner != self.order.user:
            raise ValidationError("Creator of payment order must be the same as store owner")

        if self.order.currency not in self.store.accepted_token_list.tokens.all():
            raise ValidationError(f"{self.store.name} does not accept {self.order.currency.name}")


__all__ = ["Store", "StoreRSAKeyPair", "Checkout"]
