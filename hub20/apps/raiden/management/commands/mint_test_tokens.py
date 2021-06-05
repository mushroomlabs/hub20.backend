import getpass
import logging

import ethereum
from django.core.management.base import BaseCommand
from eth_utils import to_checksum_address

from hub20.apps.blockchain.client import get_web3
from hub20.apps.blockchain.models import BaseEthereumAccount, Chain
from hub20.apps.ethereum_money.models import EthereumToken, EthereumTokenAmount, KeystoreAccount
from hub20.apps.raiden.client.blockchain import mint_tokens

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Mints tests tokens"

    def add_arguments(self, parser):
        parser.add_argument("-a", "--account", required=True, type=str)
        parser.add_argument("-t", "--token", required=True, type=str)
        parser.add_argument("--amount", default=1000, type=int)

    def handle(self, *args, **options):
        address = to_checksum_address(options["account"])
        accounts = [
            acc
            for acc in BaseEthereumAccount.objects.filter(address=address).select_subclasses()
            if acc.private_key is not None
        ]

        account = accounts and accounts.pop()

        if not account:
            private_key = getpass.getpass(f"Private Key for {address} required: ")
            generated_address = to_checksum_address(ethereum.utils.privtoaddr(private_key.strip()))
            assert generated_address == address, "Private Key does not match"
            account = KeystoreAccount(address=address, private_key=private_key)

        w3 = get_web3()
        chain_id = int(w3.net.version)
        chain = Chain.make(chain_id)

        is_mainnet = chain.id == 1
        if is_mainnet:
            logger.error("Can only mint tokens on testnets")
            return

        token = EthereumToken.make(options["token"], chain)

        amount = EthereumTokenAmount(amount=options["amount"], currency=token)
        mint_tokens(w3=w3, account=account, amount=amount)
