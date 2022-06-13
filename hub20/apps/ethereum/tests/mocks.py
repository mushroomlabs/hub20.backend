import datetime
import random
from typing import List
from unittest.mock import MagicMock

import factory
from hexbytes import HexBytes
from web3 import Web3
from web3.datastructures import AttributeDict

from ..constants import ERC20_TRANSFER_TOPIC
from ..factories import (
    TEST_CHAIN_ID,
    Erc20TokenAmountFactory,
    EtherAmountFactory,
    EthereumProvider,
    encode_transfer_data,
)

factory.Faker.add_provider(EthereumProvider)


class Web3Model(AttributeDict):
    def __init__(self, **kw):
        super().__init__(kw)


def _make_web3_mock():
    w3 = Web3()
    w3.net = MagicMock()
    w3.net.version = str(TEST_CHAIN_ID)
    w3.net.peer_count = random.randint(1, 5)
    w3.eth = MagicMock()
    w3.eth.chain_id = TEST_CHAIN_ID
    w3.provider = MagicMock()
    w3.provider.endpoint_uri = "ipc://dev/null"

    w3.isConnected = lambda: True
    return w3


def pad_hex(value: int, number_bytes: int) -> HexBytes:
    hex_value = hex(value)
    return HexBytes("0x" + hex_value[2:].zfill(number_bytes))


def pad_address(address: str) -> HexBytes:
    return HexBytes(address.replace("0x", "0x000000000000000000000000"))


def make_transfer_logs(tx_receipt_mock) -> List[Web3Model]:
    return [
        Web3Model(
            address=tx_receipt_mock.to,
            topics=[
                HexBytes(ERC20_TRANSFER_TOPIC),
                pad_address(tx_receipt_mock.from_address),
                pad_address(tx_receipt_mock.recipient),
            ],
            logIndex=0,
            blockNumber=tx_receipt_mock.blockNumber,
            blockHash=tx_receipt_mock.blockHash,
            transactionHash=tx_receipt_mock.hash,
            transactionIndex=0,
            data=pad_hex(tx_receipt_mock.amount.as_wei, 64),
        )
    ]


class Web3DataMock(factory.Factory):
    class Meta:
        model = Web3Model


class TransactionMock(Web3DataMock):
    hash = factory.Faker("hex64")
    blockHash = factory.Faker("hex64")
    blockNumber = factory.Sequence(lambda n: n)
    from_address = factory.Faker("ethereum_address")
    to = factory.Faker("ethereum_address")
    transactionIndex = 0
    gas = 21000
    gasPrice = factory.fuzzy.FuzzyInteger(1e9, 1e14)

    class Meta:
        rename = {"from_address": "from"}


class TransactionDataMock(TransactionMock):
    input = "0x0"
    nonce = factory.Sequence(lambda n: n)
    value = 0
    chainId = hex(TEST_CHAIN_ID)


class TransactionReceiptDataMock(TransactionMock):
    contractAddress = None
    logs = []
    status = 1

    class Meta:
        rename = {
            "from_address": "from",
            "hash": "transactionHash",
            "gas": "gasUsed",
            "gasPrice": "effectiveGasPrice",
        }


class BlockMock(Web3DataMock):
    difficulty = (int(1e14),)
    hash = factory.Faker("hex64")
    logsBloom = "0x0"
    nonce = factory.Sequence(lambda n: hex(n))
    number = factory.Sequence(lambda n: n)

    parentHash = factory.Faker("hex64")
    receiptRoot = factory.Faker("hex64")
    sha3Uncles = factory.Faker("hex64")
    timestamp = factory.LazyFunction(lambda: int(datetime.datetime.now().timestamp()))
    transactions = factory.LazyAttribute(
        lambda obj: [obj.tx_hash for _ in range(obj.total_transactions)]
    )
    uncles = []

    class Params:
        total_transactions = 1
        tx_hash = factory.Faker("hex64")


class BlockWithTransactionDetailsMock(BlockMock):
    transactions = factory.LazyAttribute(
        lambda obj: [
            TransactionDataMock(blockNumber=obj.number, blockHash=obj.hash, transactionIndex=idx)
            for idx in range(obj.total_transactions)
        ]
    )


class EtherTransferDataMock(TransactionDataMock):
    to = factory.LazyAttribute(lambda obj: obj.recipient)
    gas = 21000
    value = factory.LazyAttribute(lambda obj: obj.amount.as_wei)

    class Params:
        recipient = factory.Faker("ethereum_address")
        amount = factory.SubFactory(EtherAmountFactory)


class Erc20TokenTransferDataMock(TransactionDataMock):
    from_address = factory.Faker("ethereum_address")
    to = factory.LazyAttribute(lambda obj: obj.amount.currency.address)
    input = factory.LazyAttribute(
        lambda obj: encode_transfer_data(obj.recipient, obj.amount.as_wei)
    )

    class Params:
        recipient = factory.Faker("ethereum_address")
        amount = factory.SubFactory(Erc20TokenAmountFactory)


class EtherTransferReceiptMock(TransactionReceiptDataMock):
    to = factory.LazyAttribute(lambda obj: obj.recipient)
    value = factory.LazyAttribute(lambda obj: obj.amount.as_wei)

    class Params:
        recipient = factory.Faker("ethereum_address")
        amount = factory.SubFactory(Erc20TokenAmountFactory)


class Erc20TokenTransferReceiptMock(TransactionReceiptDataMock):
    to = factory.LazyAttribute(lambda obj: obj.amount.currency.address)
    logs = factory.LazyAttribute(make_transfer_logs)

    class Params:
        recipient = factory.Faker("ethereum_address")
        amount = factory.SubFactory(Erc20TokenAmountFactory)


class Erc20LogFilterMock(Web3DataMock):
    args = factory.LazyAttribute(
        lambda obj: Web3Model(_from=obj.sender, _to=obj.recipient, _value=obj.amount.as_wei)
    )
    event = "Transfer"
    logIndex = 0
    transactionIndex = factory.fuzzy.FuzzyInteger(0, 50)
    transactionHash = factory.Faker("hex64")
    address = factory.LazyAttribute(lambda obj: obj.amount.currency.address)
    blockHash = factory.Faker("hex64")
    blockNumber = factory.Sequence(lambda n: n)

    class Params:
        recipient = factory.Faker("ethereum_address")
        sender = factory.Faker("ethereum_address")
        amount = factory.SubFactory(Erc20TokenAmountFactory)


Web3Mock = _make_web3_mock()

__all__ = [
    "BlockMock",
    "BlockWithTransactionDetailsMock",
    "TransactionMock",
    "TransactionDataMock",
    "TransactionReceiptDataMock",
    "Web3Mock",
]
