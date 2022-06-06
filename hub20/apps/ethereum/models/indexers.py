import logging
import time

from django.db import models

logger = logging.getLogger(__name__)

from requests.exceptions import ReadTimeout

from .accounts import BaseWallet
from .blockchain import Chain
from .providers import Web3Provider


class ChainIndexerModel(models.Model):
    DEFAULT_BLOCK_SCAN_RANGE = 1000

    chain = models.ForeignKey(
        Chain, related_name="%(app_label)s_%(class)s_chain_indexers", on_delete=models.CASCADE
    )
    last_block = models.PositiveBigIntegerField(default=1)
    max_block_scan_range = models.PositiveIntegerField(default=DEFAULT_BLOCK_SCAN_RANGE)
    min_block_scan_range = models.PositiveIntegerField(default=DEFAULT_BLOCK_SCAN_RANGE)

    class Meta:
        abstract = True


class AccountIndexerModel(models.Model):
    account = models.ForeignKey(
        BaseWallet,
        related_name="%(app_label)s_%(class)s_account_indexers",
        on_delete=models.CASCADE,
    )

    class Meta:
        abstract = True


class AccountErc20TokenTransferIndexer(ChainIndexerModel, AccountIndexerModel):
    def __str__(self):
        return f"Erc20 transfers from wallet {self.account.address} on {self.chain_id}"

    def run(self):
        provider: Web3Provider = self.chain.provider

        if not provider:
            logger.warning(f"No provider available for {self.chain}. Stopping")

        current_block = provider.w3.eth.block_number

        if self.last_block > current_block:
            logger.warning(f"{self} is ahead of provider. Resetting and stopping")
            self.last_block = current_block
            self.save()
            return

        high_mark = self.max_block_scan_range
        low_mark = self.min_block_scan_range

        scan_range = self.max_block_scan_range

        while self.last_block < current_block:
            failed_logs = 0
            events_processed = 0

            from_block = self.last_block
            to_block = int(min(current_block, from_block + scan_range))

            logger.debug(f"Indexer {self} between {from_block}-{to_block}. ({scan_range} blocks)")

            try:
                provider.extract_native_token_transfers(from_block, to_block)
            except (TimeoutError, ReadTimeout):
                logger.error(
                    f"{provider.hostname} timeout when getting {scan_range} transfer events"
                )
                if scan_range < low_mark:
                    # This is a new low for failure. Divide in half
                    low_mark = scan_range
                    scan_range = max(1, int(scan_range / 2))
                elif low_mark < scan_range <= high_mark:
                    # A failure within the historical band
                    # Let's bring the range down a bit
                    scan_range = int((low_mark + scan_range) / 2)
                else:
                    # We tried to grab too much. Let's dial back
                    scan_range = high_mark
            else:
                blocks_processed = to_block - from_block
                logger.info(
                    f"Transfers in {blocks_processed} {provider.chain.name} blocks indexed"
                )
                logger.info(f"Logs processed: {events_processed}. Failed: {failed_logs}")
                if scan_range > high_mark:
                    # This is a new record. Let's try to be increase the amount of blocks to look
                    high_mark = scan_range
                    scan_range = int(scan_range * 1.1)
                if low_mark > scan_range:
                    # We were too timid
                    undershot = low_mark - scan_range
                    scan_range += max(1, int(undershot / 2))
                self.last_block = to_block
            finally:
                logger.info(f"Updating {self} scan parameters: max {high_mark}, min {low_mark}")
                self.min_block_scan_range = max(low_mark, 1)
                self.max_block_scan_range = max(high_mark, 1)
                self.save()


class AccountTransactionIndexer(ChainIndexerModel, AccountIndexerModel):
    MINIMUM_REQUEST_INTERVAL = 0.1

    def __str__(self):
        return f"Transaction indexers from wallet {self.account.address} on {self.chain_id}"

    def run(self):
        provider: Web3Provider = self.chain.provider

        if not provider:
            logger.warning(f"No provider available for {self.chain}. Stopping...")
            return

        if not provider.is_online:
            logger.warning(f"Provider {provider} is offline. Stopping...")
            return

        current_block = provider.w3.eth.block_number

        if self.last_block > current_block:
            logger.warning(f"{self} is ahead of provider. Resetting and stopping")
            self.last_block = current_block
            self.save()
            return

        while self.last_block < current_block:
            provider.extract_native_token_transfers(
                wallet=self.account, block_number=self.last_block
            )
            sleep_time = max(
                self.MINIMUM_REQUEST_INTERVAL,
                provider.block_creation_interval / (current_block - self.last_block),
            )
            time.sleep(sleep_time)
            self.last_block += 1
            self.save()


__all__ = ["AccountErc20TokenTransferIndexer", "AccountTransactionIndexer"]
