from typing import List, Optional

from pydantic import BaseModel

RPCProviderURL = str
FaucetURL = str


class NativeCurrency(BaseModel):
    name: str
    symbol: str
    decimals: int


class BlockchainExplorer(BaseModel):
    name: str
    url: str
    standard: str


class Chain(BaseModel):
    name: str
    chain: str
    network: Optional[str]
    icon: Optional[str]
    rpc: List[RPCProviderURL]
    faucets: List[FaucetURL]
    nativeCurrency: NativeCurrency
    infoURL: str
    shortName: str
    chainId: int
    networkId: int
    slip44: Optional[int]
    explorers: Optional[List[BlockchainExplorer]]
