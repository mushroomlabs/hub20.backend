from django.contrib.sites.models import Site

from .accounting import *  # noqa
from .networks import *  # noqa
from .payments import *  # noqa
from .store import *  # noqa
from .tokenlists import *  # noqa
from .tokens import *  # noqa
from .transfers import *  # noqa
from .user_settings import *  # noqa


def get_treasury_account():
    return Site.objects.get_current().treasury.account
