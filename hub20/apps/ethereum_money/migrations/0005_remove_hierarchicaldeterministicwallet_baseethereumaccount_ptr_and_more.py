# Generated by Django 4.0 on 2022-01-09 23:48

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ethereum_money', '0004_wrappedtoken'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='hierarchicaldeterministicwallet',
            name='baseethereumaccount_ptr',
        ),
        migrations.RemoveField(
            model_name='keystoreaccount',
            name='baseethereumaccount_ptr',
        ),
        migrations.DeleteModel(
            name='ColdWallet',
        ),
        migrations.DeleteModel(
            name='HierarchicalDeterministicWallet',
        ),
        migrations.DeleteModel(
            name='KeystoreAccount',
        ),
    ]