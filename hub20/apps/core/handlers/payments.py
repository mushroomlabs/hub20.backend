import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from hub20.apps.core import tasks
from hub20.apps.core.models import Checkout, Deposit, InternalPayment, Payment, PaymentConfirmation
from hub20.apps.core.signals import payment_received

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
        event=payment.route.network.EVENT_MESSAGES.DEPOSIT_CONFIRMED.value,
        payment_method=payment_method,
    )


@receiver(payment_received)
def on_payment_received_send_notification(sender, **kw):
    payment = kw["payment"]
    deposit = Deposit.objects.filter(routes__payments=payment).first()

    checkout = Checkout.objects.filter(order__routes__payments=payment).first()

    payment_data = dict(
        payment_id=str(payment.id),
        payment_request_id=str(payment.route.deposit.id),
    )

    deposit_received_event = payment.route.network.EVENT_MESSAGES.DEPOSIT_RECEIVED

    if deposit:
        tasks.broadcast_event.delay(event=deposit_received_event.value, **payment_data)

    if checkout:
        tasks.publish_checkout_event.delay(
            checkout.id, event=deposit_received_event.value, **payment_data
        )


__all__ = [
    "on_internal_payment_create_confirmation",
    "on_payment_confirmed_call_checkout_webhooks",
    "on_payment_confirmed_publish_checkout",
    "on_payment_received_send_notification",
]
