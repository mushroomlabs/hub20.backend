from django.dispatch import Signal

raiden_payment_received = Signal(["payment"])
raiden_payment_sent = Signal(["payment"])
service_deposit_sent = Signal(["transaction", "raiden", "amount", "contract_address"])
