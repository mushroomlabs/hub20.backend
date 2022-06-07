from typing import NewType, Union

from hexbytes import HexBytes

from .models.fields import EthereumAddressField

Address = Union[str, EthereumAddressField]

ChainID_T = int
ChainID = NewType("ChainID", ChainID_T)

TransactionHash_T = HexBytes
TransactionHash = NewType("TransactionHash", TransactionHash_T)
