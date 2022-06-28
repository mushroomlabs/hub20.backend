import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from hub20.apps.core import tasks
from hub20.apps.core.models import Checkout, InternalPayment, PaymentConfirmation
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


@receiver(payment_received)
def on_payment_received_broadcast_event(sender, **kw):
    payment = kw["payment"]
    payment_data = dict(
        payment_id=str(payment.id),
        payment_request_id=str(payment.route.deposit.id),
    )
    tasks.broadcast_event.delay(
        event=payment.route.network.EVENT_MESSAGES.DEPOSIT_RECEIVED.value, **payment_data
    )


@receiver(payment_received)
def on_payment_received_notify_checkout(sender, **kw):
    payment = kw["payment"]
    checkout = Checkout.objects.filter(order__routes__payments=payment).first()

    if checkout:
        payment_data = dict(
            payment_id=str(payment.id),
            payment_request_id=str(payment.route.deposit.id),
        )

        tasks.publish_checkout_event.delay(
            checkout.id,
            event=payment.route.network.EVENT_MESSAGES.DEPOSIT_RECEIVED.value,
            **payment_data,
        )


@receiver(post_save, sender=PaymentConfirmation)
def on_payment_confirmed_broadcast_event(sender, **kw):
    if not kw["created"]:
        return

    confirmation = kw["instance"]
    payment = confirmation.payment.subclassed

    payment_data = dict(
        payment_id=str(payment.id),
        payment_request_id=str(payment.route.deposit.id),
    )
    tasks.broadcast_event.delay(
        event=payment.route.network.EVENT_MESSAGES.DEPOSIT_CONFIRMED.value, **payment_data
    )


@receiver(post_save, sender=PaymentConfirmation)
def on_payment_confirmed_notify_checkout(sender, **kw):
    if not kw["created"]:
        return

    confirmation = kw["instance"]
    payment = confirmation.payment.subclassed

    checkout = Checkout.objects.filter(order__routes__payments__confirmation=confirmation).first()

    if checkout is None:
        return

    payment_data = dict(
        payment_id=str(payment.id),
        payment_request_id=str(checkout.order.id),
    )

    tasks.publish_checkout_event.delay(
        checkout.id,
        event=payment.route.network.EVENT_MESSAGES.DEPOSIT_CONFIRMED.value,
        **payment_data,
    )


__all__ = [
    "on_internal_payment_create_confirmation",
    "on_payment_confirmed_call_checkout_webhooks",
    "on_payment_received_broadcast_event",
    "on_payment_received_notify_checkout",
    "on_payment_confirmed_broadcast_event",
    "on_payment_confirmed_notify_checkout",
]
