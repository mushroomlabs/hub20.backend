import getpass
import logging

import ethereum
from django.core.management.base import BaseCommand
from eth_utils import to_checksum_address

from hub20.apps.core.models import TokenAmount
from hub20.apps.ethereum.models import BaseWallet, Chain, KeystoreAccount

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Calls mint function on tokens (should only work for test tokens)"

    def add_arguments(self, parser):
        parser.add_argument("-a", "--account", required=True, type=str)
        parser.add_argument("-t", "--token", required=True, type=str)
        parser.add_argument("--amount", default=1000, type=int)
        parser.add_argument("--chain-id", "-c", dest="chain_id", required=True, type=int)

    def handle(self, *args, **options):
        address = to_checksum_address(options["account"])
        account = BaseWallet.objects.filter(address=address).first()

        if not (account and getattr(account, "private_key", None)):
            private_key = getpass.getpass(f"Private Key for {address} required: ")
            generated_address = to_checksum_address(ethereum.utils.privtoaddr(private_key.strip()))
            assert generated_address == address, "Private Key does not match"
            account = KeystoreAccount(address=address, private_key=private_key)

        chain = Chain.objects.get(id=options["chain_id"])
        if not chain.is_testnet:
            logger.error("Can only mint tokens on testnets")
            return

        token = chain.provider.save_token(options["token"])

        amount = TokenAmount(amount=options["amount"], currency=token)
        chain.provider.mint_tokens(account=account, amount=amount)
