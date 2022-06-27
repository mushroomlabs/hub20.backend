from enum import Enum

NULL_ADDRESS: str = "0x" + "0" * 40
SENTINEL_ADDRESS: str = "0x" + "0" * 39 + "1"

# keccak('Transfer(address,address,uint256)')
ERC20_TRANSFER_TOPIC: str = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class Events(Enum):
    BLOCK_CREATED = "ethereum.block.created"
    DEPOSIT_BROADCAST = "ethereum.deposit.broadcast"
