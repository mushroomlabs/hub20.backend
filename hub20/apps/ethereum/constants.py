from enum import Enum

from ethereum.transactions import secpk1n

NULL_ADDRESS: str = "0x" + "0" * 40
SENTINEL_ADDRESS: str = "0x" + "0" * 39 + "1"

# keccak('Transfer(address,address,uint256)')
ERC20_TRANSFER_TOPIC: str = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

SIGNATURE_R_MIN_VALUE: int = 1
SIGNATURE_R_MAX_VALUE: int = secpk1n - 1
SIGNATURE_S_MIN_VALUE: int = 1
SIGNATURE_S_MAX_VALUE: int = secpk1n // 2
SIGNATURE_V_MIN_VALUE: int = 27
SIGNATURE_V_MAX_VALUE: int = 28


class Events(Enum):
    BLOCK_CREATED = "ethereum.block.created"
    DEPOSIT_RECEIVED = "ethereum.deposit.received"
    DEPOSIT_BROADCAST = "ethereum.deposit.broadcast"
    DEPOSIT_CONFIRMED = "ethereum.deposit.confirmed"
    ROUTE_EXPIRED = "ethereum.route.expired"
    PROVIDER_OFFLINE = "ethereum.provider.offline"
    PROVIDER_ONLINE = "ethereum.provider.online"
