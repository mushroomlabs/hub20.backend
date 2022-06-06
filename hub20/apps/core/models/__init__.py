from django.contrib.sites.models import Site

from .accounting import *  # noqa
from .accounting import PaymentNetworkAccount
from .checkout import *  # noqa
from .networks import *  # noqa
from .payments import *  # noqa
from .payments import InternalPaymentNetwork
from .providers import *  # noqa
from .tokenlists import *  # noqa
from .tokens import *  # noqa
from .transfers import *  # noqa
from .user_settings import *  # noqa


def get_treasury_account():
    site = Site.objects.get_current()
    network, _ = InternalPaymentNetwork.objects.get_or_create(
        site=site,
        defaults=dict(
            name=f"{site.name} Internal Payment Network",
            description="To manage accounting entries for all in-hub operations",
        ),
    )
    account, _ = PaymentNetworkAccount.objects.get_or_create(network=network)

    return account
