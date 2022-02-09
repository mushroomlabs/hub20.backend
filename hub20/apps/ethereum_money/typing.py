from decimal import Decimal
from typing import TypeVar, Union

Wei = int
TokenAmount = Decimal

Web3Client_T = TypeVar("Web3Client_T")
TokenAmount_T = Union[int, float, Decimal, TokenAmount, Wei]
