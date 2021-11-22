import json

from django.apps import AppConfig
from kombu.serialization import register
from web3 import Web3
from web3.datastructures import AttributeDict


def dump_web3_data(web3_data: AttributeDict):
    return web3_data and Web3.toJSON(web3_data)


def load_web3_data(json_data):
    return json.loads(json_data)
    # return AttributeDict(json.loads(json_data.decode()))


class BlockchainConfig(AppConfig):
    name = "hub20.apps.blockchain"

    def ready(self):
        from . import handlers  # noqa
        from . import signals  # noqa

        register(
            "web3",
            dump_web3_data,
            load_web3_data,
            content_type="application/json+web3",
            content_encoding="utf-8",
        )
