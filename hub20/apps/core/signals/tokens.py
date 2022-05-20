from django.dispatch import Signal

incoming_transfer_broadcast = Signal(["account", "amount", "transaction_data"])
incoming_transfer_mined = Signal(["account", "transaction", "amount", "address"])
outgoing_transfer_broadcast = Signal(["account", "amount", "transaction_data"])
outgoing_transfer_mined = Signal(["account", "transaction", "amount", "address"])


__all__ = [
    "incoming_transfer_broadcast",
    "incoming_transfer_mined",
    "outgoing_transfer_broadcast",
    "outgoing_transfer_mined",
]
