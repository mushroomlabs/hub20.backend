import logging
from typing import Optional

from django.contrib.sessions.models import Session
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from hub20.apps.core import tasks
from hub20.apps.core.models import Checkout, InternalPayment, Payment, PaymentConfirmation
from hub20.apps.wallet import get_wallet_model

logger = logging.getLogger(__name__)
Wallet = get_wallet_model()


def _get_user_id(session: Session) -> Optional[int]:
    try:
        return int(session.get_decoded()["_auth_user_id"])
    except (KeyError, ValueError, TypeError):
        return None


def _get_user_session_keys(user_id):
    now = timezone.now()
    sessions = Session.objects.filter(expire_date__gt=now)
    return [s.session_key for s in sessions if _get_user_id(s) == user_id]


@receiver(post_save, sender=InternalPayment)
def on_internal_payment_create_confirmation(sender, **kw):
    if kw["created"]:
        PaymentConfirmation.objects.create(payment=kw["instance"])


@receiver(post_save, sender=PaymentConfirmation)
def on_payment_confirmed_call_checkout_webhooks(sender, **kw):
    confirmation = kw["instance"]

    checkouts = Checkout.objects.filter(order__routes__payments__confirmation=confirmation)
    for checkout_id in checkouts.values_list("id", flat=True):
        tasks.call_checkout_webhook.delay(checkout_id)


@receiver(post_save, sender=PaymentConfirmation)
def on_payment_confirmed_publish_checkout(sender, **kw):
    if not kw["created"]:
        return

    confirmation = kw["instance"]
    payment = Payment.objects.filter(id=confirmation.payment_id).select_subclasses().first()

    if not payment:
        return

    checkouts = Checkout.objects.filter(order__routes__payments=payment)
    checkout_id = checkouts.values_list("id", flat=True).first()

    if checkout_id is None:
        return

    payment_method = payment.route.network

    tasks.publish_checkout_event.delay(
        checkout_id,
        amount=str(payment.amount),
        token=payment.currency.address,
        event="{payment_method}.deposit.confirmed",
        payment_method=payment_method,
    )


__all__ = [
    "on_internal_payment_create_confirmation",
    "on_payment_confirmed_call_checkout_webhooks",
    "on_payment_confirmed_publish_checkout",
]
