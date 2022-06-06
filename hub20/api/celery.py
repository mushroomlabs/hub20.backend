import os

from celery import Celery
from celery.schedules import crontab
from django.conf import settings


class Hub20CeleryConfig:
    name = "Hub20"

    broker_url = "memory" if "HUB20_TEST" in os.environ else settings.CELERY_BROKER_URL
    broker_use_ssl = "HUB20_BROKER_USE_SSL" in os.environ
    beat_schedule = {
        "clear-expired-sessions": {
            "task": "hub20.apps.core.tasks.clear_expired_sessions",
            "schedule": crontab(minute="*/30"),
            "expires": 60,
        },
        # "refresh-wallet-balances": {
        #     "task": "hub20.apps.wallet.tasks.update_all_wallet_balances",
        #     "schedule": crontab(minute=0),
        #     "expires": BLOCK_CREATION_INTERVAL,
        # },
        # "execute-transfers": {
        #     "task": "hub20.apps.core.tasks.execute_pending_transfers",
        #     "schedule": crontab(),
        #     "expires": 60,
        # },
        # "sync-raiden-channels": {
        #     "task": "hub20.apps.raiden.tasks.sync_channels",
        #     "schedule": crontab(minute="*/5"),
        #     "expires": 5 * 60,
        # },
        # "sync-raiden-payments": {
        #     "task": "hub20.apps.raiden.tasks.sync_payments",
        #     "schedule": timedelta(seconds=RAIDEN_PAYMENT_CHECK_INTERVAL),
        #     "expires": RAIDEN_PAYMENT_CHECK_INTERVAL,
        # },
        # "check-payments-in-open-routes": {
        #     "task": "hub20.apps.core.tasks.check_payments_in_open_routes",
        #     "schedule": timedelta(seconds=BLOCK_CREATION_INTERVAL),
        #     "expires": BLOCK_CREATION_INTERVAL,
        # },
    }
    result_backend = "django-db"
    task_always_eager = "HUB20_TEST" in os.environ
    task_eager_propagates = "HUB20_TEST" in os.environ
    task_ignore_result = True
    accept_content = ["json"]


app = Celery()
app.config_from_object(Hub20CeleryConfig)
app.autodiscover_tasks()
