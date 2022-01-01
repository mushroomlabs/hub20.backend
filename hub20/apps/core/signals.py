from django.dispatch import Signal

order_canceled = Signal(["order", "request"])
payment_received = Signal(["payment"])

__all__ = [
    "order_canceled",
    "payment_received",
]
