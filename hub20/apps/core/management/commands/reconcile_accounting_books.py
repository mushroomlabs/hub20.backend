import logging

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db.models import QuerySet
from web3 import Web3

from hub20.apps.blockchain.app_settings import BLOCK_SCAN_RANGE
from hub20.apps.blockchain.client import make_web3
from hub20.apps.blockchain.models import BaseEthereumAccount, Chain, Transaction, Web3Provider
from hub20.apps.core.models.accounting import (
    ExternalAddressAccount,
    RaidenClientAccount,
    Treasury,
    UserAccount,
    WalletAccount,
)
from hub20.apps.ethereum_money.client import (
    index_account_erc20_approvals,
    index_account_erc20_transfers,
    index_account_erc223_transactions,
)
from hub20.apps.ethereum_money.models import EthereumToken
from hub20.apps.raiden.client.blockchain import (
    get_all_channel_deposits,
    get_all_service_deposits,
    index_all_token_network_events,
)
from hub20.apps.raiden.models import Payment as RaidenPayment, Raiden

User = get_user_model()
logger = logging.getLogger(__name__)


def index_token_events(w3: Web3, chain: Chain, accounts: QuerySet, tokens: QuerySet):
    starting_block = 0

    while starting_block < chain.highest_block:
        for token in tokens:
            chain = token.chain
            for account in accounts:
                end_block = min(starting_block + BLOCK_SCAN_RANGE, chain.highest_block)
                index_account_erc20_approvals(
                    w3=w3,
                    account=account,
                    token=token,
                    starting_block=starting_block,
                    end_block=end_block,
                )
                index_account_erc20_transfers(
                    w3=w3,
                    account=account,
                    token=token,
                    starting_block=starting_block,
                    end_block=end_block,
                )
                index_account_erc223_transactions(
                    w3=w3,
                    account=account,
                    token=token,
                    starting_block=starting_block,
                    end_block=end_block,
                )
        starting_block += BLOCK_SCAN_RANGE


class Command(BaseCommand):
    help = "Sets up accounting books and reconciles transactions and raiden payments"

    def handle(self, *args, **options):
        accounts = BaseEthereumAccount.objects.all()
        transaction_type = ContentType.objects.get_for_model(Transaction)

        for user in User.objects.all():
            UserAccount.objects.get_or_create(user=user)

        for wallet in accounts:
            WalletAccount.objects.get_or_create(account=wallet)

        # Index Transactions
        for provider in Web3Provider.available.all():
            chain = provider.chain
            w3 = make_web3(provider=provider)
            Treasury.objects.get_or_create(chain=chain)

            native_token = EthereumToken.make_native(chain=chain)
            tokens = EthereumToken.ERC20tokens.filter(chain=chain)

            index_token_events(w3=w3, chain=chain, accounts=accounts, tokens=tokens)
            index_all_token_network_events(w3=w3)

            for raiden in Raiden.objects.all():
                RaidenClientAccount.objects.get_or_create(raiden=raiden)
                get_all_service_deposits(w3=w3, raiden=raiden)
                get_all_channel_deposits(w3=w3, raiden=raiden)

            # Native Token Value Transfers
            for account in accounts:
                wallet_book = account.onchain_account.get_book(token=native_token)

                # Ethereum Transactions Received
                for tx in account.transactions.filter(to_address=account.address, value__gt=0):
                    amount = native_token.from_wei(tx.value)
                    params = dict(
                        reference_type=transaction_type,
                        reference_id=tx.id,
                        currency=native_token,
                        amount=amount.amount,
                    )
                    external_address_account, _ = ExternalAddressAccount.objects.get_or_create(
                        address=tx.from_address
                    )
                    external_address_book = external_address_account.get_book(token=native_token)

                    external_address_book.debits.get_or_create(**params)
                    wallet_book.credits.get_or_create(**params)

                # Ethereum Transactions Sent
                for tx in account.transactions.filter(from_address=account.address, value__gt=0):
                    amount = native_token.from_wei(tx.value)
                    params = dict(
                        reference_type=transaction_type,
                        reference_id=tx.id,
                        currency=native_token,
                        amount=amount.amount,
                    )
                    external_address_account, _ = ExternalAddressAccount.objects.get_or_create(
                        address=tx.to_address
                    )

                    external_address_book = external_address_account.get_book(token=ETH)

                    external_address_book.credits.get_or_create(**params)
                    wallet_book.debits.get_or_create(**params)

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

                    external_address_account, _ = ExternalAddressAccount.objects.get_or_create(
                        address=payment.partner_address
                    )

                    external_account_book = external_address_account.get_book(token=payment.token)
                    raiden_book = raiden.raiden_account.get_book(token=payment.token)

                    if payment.is_outgoing:
                        raiden_book.debits.get_or_create(**params)
                        external_account_book.credits.get_or_create(**params)
                    else:
                        external_account_book.debits.get_or_create(**params)
                        raiden_book.credits.get_or_create(**params)
