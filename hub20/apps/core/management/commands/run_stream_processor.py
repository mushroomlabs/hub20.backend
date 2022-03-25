import logging

from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs any function that is meant to be work as a stream processor"

    def add_arguments(self, parser):
        parser.add_argument("processor", type=import_string)

    def handle(self, *args, **options):
        try:
            options["processor"]()
        except KeyboardInterrupt:
            pass
