from decimal import Decimal
from typing import TypeVar, Union

Wei = int
TokenAmount = Decimal

EthereumClient_T = TypeVar("EthereumClient_T")
TokenAmount_T = Union[int, float, Decimal, TokenAmount, Wei]
