from django.dispatch import Signal

block_sealed = Signal(providing_args=["chain_id", "block_data"])
chain_status_synced = Signal(providing_args=["chain_id", "current_block", "synced"])
chain_reorganization_detected = Signal(providing_args=["chain_id", "new_block_height"])
transaction_broadcast = Signal(providing_args=["chain_id", "transaction_data"])
transaction_mined = Signal(
    providing_args=["chain_id", "block_data", "transaction_data", "transaction_receipt"]
)
