from django.dispatch import Signal

block_sealed = Signal(["chain_id", "block_data"])
chain_status_synced = Signal(["chain_id", "current_block", "synced"])
chain_reorganization_detected = Signal(["chain_id", "new_block_height"])
transaction_broadcast = Signal(["chain_id", "transaction_data"])
