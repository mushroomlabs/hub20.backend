# Generated by Django 4.0 on 2022-01-18 10:11

from django.db import migrations


def prune_tx_table(apps, schema_editor):
    """
    We are not going to need any transactions that are not related
    to any account
    """
    Transaction = apps.get_model("blockchain", "Transaction")

    Transaction.objects.filter(baseethereumaccount__transactions__isnull=True).delete()


def split_transaction_records(apps, schema_editor):
    Transaction = apps.get_model("blockchain", "Transaction")
    TransactionDataRecord = apps.get_model("blockchain", "TransactionDataRecord")

    for tx in Transaction.objects.all():
        TransactionDataRecord.objects.create(
            hash=tx.hash,
            chain=tx.block.chain,
            from_address=tx.from_address,
            to_address=tx.to_address,
            data={
                "from": tx.from_address,
                "to": tx.to_address,
                "hash": tx.hash,
                "blockHash": tx.block.hash,
                "blockNumber": tx.block.number,
                "transactionIndex": tx.index,
                "gasPrice": tx.gas_price,
                "input": tx.data,
            },
        )
        tx.receipt = {
            "from": tx.from_address,
            "to": tx.to_address,
            "transactionHash": tx.hash,
            "blockHash": tx.block.hash,
            "blockNumber": tx.block.number,
            "transactionIndex": tx.index,
            "gasUsed": tx.gas_used,
            "effectiveGasPrice": tx.gas_price,
            "status": int(tx.success),
        }
        tx.save()


class Migration(migrations.Migration):

    dependencies = [
        ("blockchain", "0019_transactiondatarecord_and_more"),
    ]

    operations = [
        migrations.RunPython(prune_tx_table, migrations.RunPython.noop),
        migrations.RunPython(split_transaction_records, migrations.RunPython.noop),
    ]
