from typing import NewType, TypeVar, Union

from hexbytes import HexBytes

from hub20.apps.core.fields import EthereumAddressField
from hub20.apps.core.models.tokens import BaseToken

Address = Union[str, EthereumAddressField]

EthereumAccount_T = TypeVar("EthereumAccount_T")

ChainID_T = int
ChainID = NewType("ChainID", ChainID_T)

TransactionHash_T = HexBytes
TransactionHash = NewType("TransactionHash", TransactionHash_T)

Web3Client_T = TypeVar("Web3Client_T")

Token_T = TypeVar("Token_T", bound=BaseToken)
