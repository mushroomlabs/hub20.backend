from django.dispatch import Signal

order_canceled = Signal(providing_args=["order", "request"])
payment_received = Signal(providing_args=["payment"])

__all__ = [
    "order_canceled",
    "payment_received",
]
