from django.dispatch import Signal

block_sealed = Signal(["chain_id", "block_data"])
chain_status_synced = Signal(["chain_id", "current_block", "synced"])
chain_reorganization_detected = Signal(["chain_id", "new_block_height"])
incoming_transfer_broadcast = Signal(["account", "amount", "transaction_data"])
outgoing_transfer_broadcast = Signal(["account", "amount", "transaction_data"])
outgoing_transfer_mined = Signal(["account", "transaction", "amount", "address"])
wallet_generated = Signal(["wallet"])


__all__ = [
    "block_sealed",
    "chain_status_synced",
    "chain_reorganization_detected",
    "incoming_transfer_broadcast",
    "outgoing_transfer_broadcast",
    "outgoing_transfer_mined",
    "wallet_generated",
]
