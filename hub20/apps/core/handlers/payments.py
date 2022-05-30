import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from hub20.apps.core import tasks
from hub20.apps.core.models import Checkout, InternalPayment, Payment, PaymentConfirmation

logger = logging.getLogger(__name__)


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

    payment_method = payment.route.network.type

    tasks.publish_checkout_event.delay(
        checkout_id,
        amount=str(payment.amount),
        token=payment.currency.pk,
        event=f"{payment_method}.deposit.confirmed",
        payment_method=payment_method,
    )


__all__ = [
    "on_internal_payment_create_confirmation",
    "on_payment_confirmed_call_checkout_webhooks",
    "on_payment_confirmed_publish_checkout",
]
