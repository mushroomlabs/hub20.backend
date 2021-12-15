import logging
from statistics import StatisticsError, mean

from django.conf import settings
from django.core.cache import cache
from qr3.qr import CappedCollection
from redis.connection import parse_url

logger = logging.getLogger(__name__)

BLOCK_HISTORY_COLLECTION_SIZE = 200

CACHE_CONNECTION_PARAMS = parse_url(settings.CACHE_LOCATION)


class MaxPriorityFeeTracker:
    CACHE_KEY_TEMPLATE = "hub20:blockchain:analytics:MAX_PRIORITY_FEE_{chain_id}"

    def _get_cache_key(self, chain_id):
        return self.CACHE_KEY_TEMPLATE.format(chain_id=chain_id)

    def get(self, chain_id):
        return cache.get(self._get_cache_key(chain_id), None)

    def set(self, chain_id, value):
        return cache.set(self._get_cache_key(chain_id), value)


def recommended_eip1559_gas_price(block_data, max_priority_fee=None):
    # Formula follows the simple heuristic described on
    # https://www.blocknative.com/blog/eip-1559-fees. We might want to improve on this later

    try:
        return (2 * block_data.baseFeePerGas) + (max_priority_fee or 0)
    except AttributeError:
        raise ValueError("block does not contain EIP-1559 'baseFeePerGas' field")


def mean_gas_price(block_data):
    try:
        return mean(
            [
                p
                for p in [getattr(t, "gasPrice", None) for t in block_data.transactions]
                if p is not None
            ]
        )
    except StatisticsError:
        return None


def get_historical_block_data(chain_id):
    return CappedCollection(
        f"Blocks:{chain_id}", BLOCK_HISTORY_COLLECTION_SIZE, **CACHE_CONNECTION_PARAMS
    )


def estimate_gas_price(chain_id):
    historical_data = get_historical_block_data(chain_id)
    blocks = historical_data.elements()

    if not blocks:
        return None

    most_recent_block = blocks[0]

    if getattr(most_recent_block, "baseFeePerGas", None):
        # Supports EIP-1559.
        return recommended_eip1559_gas_price(
            most_recent_block, max_priority_fee=MAX_PRIORITY_FEE_TRACKER.get(chain_id)
        )

    # No support for EIP-1559, so we will look at the gas price of all
    # transactions in the N blocks and take a weighted average by the blocks age

    price_history = enumerate([mean_gas_price(block) for block in blocks[::-1]])

    weighted_prices = [age * price for (age, price) in price_history if price is not None]
    denominator = (len(blocks) + 1) * (len(blocks) / 2)

    return int(sum(weighted_prices) / denominator)


MAX_PRIORITY_FEE_TRACKER = MaxPriorityFeeTracker()
