from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def get_wallet_model():
    """
    Return the Wallet model that is active in this project.
    """

    account_setting = getattr(settings, "WALLET_MODEL", "wallet.ColdWallet")

    try:
        return django_apps.get_model(account_setting, require_ready=False)
    except ValueError:
        raise ImproperlyConfigured("WALLET_MODEL must be of the form 'app_label.model_name'")
    except LookupError:
        raise ImproperlyConfigured(
            f"Model '{account_setting}' is not installed and can not be used as Ethereum Account"
        )
