from typing import NewType, TypeVar, Union

from hexbytes import HexBytes

from .fields import AddressField

Address = Union[str, AddressField]

EthereumAccount_T = TypeVar("EthereumAccount_T")

ChainID_T = int
ChainID = NewType("ChainID", ChainID_T)

TransactionHash_T = HexBytes
TransactionHash = NewType("TransactionHash", TransactionHash_T)

Web3Client_T = TypeVar("Web3Client_T")
