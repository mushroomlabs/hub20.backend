from django.dispatch import Signal

raiden_payment_received = Signal(["payment"])
raiden_payment_sent = Signal(["payment"])
