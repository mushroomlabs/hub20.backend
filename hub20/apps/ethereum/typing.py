from typing import NewType, TypeVar, Union

from hexbytes import HexBytes

from .models.fields import EthereumAddressField

Address = Union[str, EthereumAddressField]

EthereumAccount_T = TypeVar("EthereumAccount_T")

ChainID_T = int
ChainID = NewType("ChainID", ChainID_T)

TransactionHash_T = HexBytes
TransactionHash = NewType("TransactionHash", TransactionHash_T)

Web3Client_T = TypeVar("Web3Client_T")
