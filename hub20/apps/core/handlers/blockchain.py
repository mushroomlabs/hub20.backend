from django.db.models.signals import post_save
from django.dispatch import receiver

from hub20.apps.core.models.blockchain import Chain, ChainMetadata


@receiver(post_save, sender=Chain)
def on_chain_created_create_metadata_entry(sender, **kw):
    if kw["created"]:
        ChainMetadata.objects.get_or_create(chain=kw["instance"])


__all__ = ["on_chain_created_create_metadata_entry"]
