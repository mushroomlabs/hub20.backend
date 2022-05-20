import json
import uuid
from decimal import Decimal

from hexbytes import HexBytes
from web3.datastructures import AttributeDict


class Web3Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, AttributeDict):
            return {
                "__type__": "attrdict",
                "value": json.dumps({k: v for k, v in obj.items()}, cls=self.__class__),
            }
        elif isinstance(obj, bytes):
            return {"__type__": "bytes", "value": obj.hex()}
        elif isinstance(obj, HexBytes):
            return {"__type__": "hexbytes", "value": obj.hex()}
        elif isinstance(obj, uuid.UUID):
            return {"__type__": "uuid", "value": str(obj)}
        elif isinstance(obj, Decimal):
            return {"__type__": "decimal", "value": str(obj)}
        else:
            return json.JSONEncoder.default(self, obj)


def web3_decoder(obj):
    try:
        if obj["__type__"] == "attrdict":
            return AttributeDict(json.loads(obj["value"], object_hook=web3_decoder))
        elif obj["__type__"] == "hexbytes":
            return HexBytes(obj["value"])
        elif obj["__type__"] == "bytes":
            return bytes(HexBytes(obj["value"]))
        elif obj["__type__"] == "uuid":
            return uuid.UUID(obj["value"])
        elif obj["__type__"] == "decimal":
            return Decimal(obj["value"])
        else:
            return obj
    except KeyError:
        return obj


def web3_serializer(obj):
    return json.dumps(obj, cls=Web3Encoder)


def web3_deserializer(obj):
    return json.loads(obj, object_hook=web3_decoder)
