from typing import TypeVar, Union

from hexbytes import HexBytes

from .fields import EthereumAddressField

Address = Union[str, HexBytes, EthereumAddressField]
EthereumAccount_T = TypeVar("EthereumAccount_T")
TransactionHash = HexBytes
