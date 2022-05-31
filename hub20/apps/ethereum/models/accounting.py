import logging
import uuid

from django.db import models

from hub20.apps.core.models import TokenValueModel

from .blockchain import Transaction

logger = logging.getLogger(__name__)


class TransactionFee(TokenValueModel):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="fee")


__all__ = ["TransactionFee"]
