from django import forms
from requests.exceptions import ConnectionError

from hub20.apps.core.forms import TokenForm

from .models import BlockchainPaymentNetwork, Erc20Token, NativeToken, Web3Provider
from .models.providers import get_web3
from .validators import web3_url_validator


class Web3URLField(forms.URLField):
    default_validators = [web3_url_validator]


class NativeTokenForm(TokenForm):
    class Meta:
        model = NativeToken
        fields = ("chain", "symbol", "name", "decimals", "logoURI", "is_listed")


class Erc20TokenForm(TokenForm):
    class Meta:
        model = Erc20Token
        fields = ("chain", "address", "symbol", "name", "decimals", "logoURI", "is_listed")


class Web3ProviderForm(forms.ModelForm):
    def clean(self):
        cleaned_data = super().clean()
        w3 = get_web3(cleaned_data["url"], timeout=Web3Provider.DEFAULT_REQUEST_TIMEOUT)

        try:
            chain_id = w3.eth.chain_id
            self.network = BlockchainPaymentNetwork.objects.get(chain__id=chain_id)
        except BlockchainPaymentNetwork.DoesNotExist:
            self.add_error(
                "url", f"Node reported connection to Chain ID {chain_id}, which we do not know"
            )
        except ConnectionError:
            self.add_error("url", "Could not connect to the provided url")
        except Exception as exc:
            self.add_error("url", f"Not a valid web3 provider url: {exc}")

    def save(self, *args, **kw):
        self.instance.network = self.network
        return super().save(*args, **kw)

    class Meta:
        model = Web3Provider
        fields = ("network", "url", "max_block_scan_range", "is_active", "connected", "synced")
        field_classes = {"url": Web3URLField}
