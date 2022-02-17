from model_utils import Choices

DEPOSIT_STATUS = Choices("open", "paid", "confirmed", "expired")
TRANSFER_STATUS = Choices("scheduled", "processed", "failed", "canceled", "confirmed")
PAYMENT_NETWORKS = Choices("internal", "blockchain", "raiden")

WITHDRAWAL_NETWORKS = Choices("blockchain", "raiden")
