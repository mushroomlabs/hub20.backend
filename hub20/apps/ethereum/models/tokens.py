import json
import logging

import requests
from django.db import models

from hub20.apps.core.models import BaseToken, TokenList

from ..constants import NULL_ADDRESS
from ..schemas import TokenList as TokenListSchema, validate_token_list
from .blockchain import Chain
from .fields import EthereumAddressField

logger = logging.getLogger(__name__)


# Tokens
class NativeToken(BaseToken):
    chain = models.OneToOneField(Chain, on_delete=models.CASCADE, related_name="native_token")

    def __str__(self) -> str:
        return f"{self.name} ({self.symbol}): Native Token @ {self.chain_id}"

    @property
    def natural_data(self):
        return dict(name=self.name, symbol=self.symbol, chain_id=self.chain_id)

    @property
    def address(self):
        return NULL_ADDRESS


class Erc20Token(BaseToken):

    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name="tokens")
    address = EthereumAddressField()

    def __str__(self) -> str:
        return f"{self.name} ({self.symbol}): {self.address} @ {self.chain_id}"

    @property
    def natural_data(self):
        return dict(
            name=self.name, symbol=self.symbol, chain_id=self.chain_id, address=self.address
        )

    @classmethod
    def make(cls, address: str, chain: Chain, **defaults):
        obj, _ = cls.objects.update_or_create(address=address, chain=chain, defaults=defaults)
        return obj

    @classmethod
    def load_tokenlist(cls, url, description=None):
        response = requests.get(url)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            raise ValueError(f"Failed to fetch {url}")

        try:
            response_data = response.json()
        except json.decoder.JSONDecodeError:
            raise ValueError(f"Could not decode json response from {url}")

        validate_token_list(response_data)

        token_list_data: TokenListSchema = TokenListSchema(**response_data)

        token_list, _ = TokenList.objects.get_or_create(
            url=url,
            version=token_list_data.version.as_string,
            defaults=dict(name=token_list_data.name),
        )
        token_list.description = description
        token_list.keywords.add(*token_list_data.keywords)
        token_list.save()

        for token_entry in token_list_data.tokens:
            token, _ = cls.objects.get_or_create(
                chain_id=token_entry.chainId,
                address=token_entry.address,
                defaults=dict(
                    name=token_entry.name,
                    decimals=token_entry.decimals,
                    symbol=token_entry.symbol,
                    logoURI=token_entry.logoURI,
                ),
            )
            token_list.tokens.add(token)
        return token_list

    class Meta:
        unique_together = (("chain", "address"),)


__all__ = ["NativeToken", "Erc20Token"]
