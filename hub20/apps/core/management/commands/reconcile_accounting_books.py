import logging

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from hub20.apps.blockchain.models import Transaction
from hub20.apps.core.choices import PAYMENT_NETWORKS
from hub20.apps.core.models.accounting import PaymentNetworkAccount, UserAccount
from hub20.apps.ethereum_money.models import EthereumToken, TransferEvent
from hub20.apps.raiden.models import Payment as RaidenPayment, Raiden
from hub20.apps.wallet.models import Wallet

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sets up accounting books and reconciles transactions and raiden payments"

    def handle(self, *args, **options):
        treasury = PaymentNetworkAccount.make(PAYMENT_NETWORKS.internal)
        blockchain_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.blockchain)
        raiden_account = PaymentNetworkAccount.make(PAYMENT_NETWORKS.raiden)
        transaction_type = ContentType.objects.get_for_model(Transaction)

        for user in User.objects.all():
            UserAccount.objects.get_or_create(user=user)

        tokens = EthereumToken.objects.filter(transferevent__currency__isnull=False)

        wallet_addresses = Wallet.objects.values_list("address", flat=True)

        for token in tokens:
            treasury_book = treasury.get_book(token=token)
            blockchain_book = blockchain_account.get_book(token=token)

            for transfer in TransferEvent.objects.filter(
                currency=token, sender__in=wallet_addresses
            ):
                params = dict(
                    reference_type=transaction_type,
                    reference_id=transfer.transaction_id,
                    currency=transfer.currency,
                    amount=transfer.amount,
                )

                blockchain_book.credits.get_or_create(**params)
                treasury_book.debits.get_or_create(**params)

            for transfer in TransferEvent.objects.filter(
                currency=token, recipient__in=wallet_addresses
            ):
                params = dict(
                    reference_type=transaction_type,
                    reference_id=transfer.transaction_id,
                    currency=transfer.currency,
                    amount=transfer.amount,
                )

                treasury_book.credits.get_or_create(**params)
                blockchain_book.debits.get_or_create(**params)

        # Raiden payments
        for raiden in Raiden.objects.all():
            payment_type = ContentType.objects.get_for_model(RaidenPayment)
            for channel in raiden.channels.all():
                logger.info(f"Recording entries for {channel}")
                for payment in channel.payments.all():
                    logger.info(f"Recording entries for {payment}")
                    params = dict(
                        reference_type=payment_type,
                        reference_id=payment.id,
                        amount=payment.amount,
                        currency=payment.token,
                    )

                    raiden_book = raiden_account.get_book(token=payment.token)
                    treasury_book = treasury.get_book(token=payment.token)

                    if payment.is_outgoing:
                        raiden_book.credits.get_or_create(**params)
                        treasury_book.debits.get_or_create(**params)
                    else:
                        treasury_book.credits.get_or_create(**params)
                        raiden_book.debits.get_or_create(**params)
