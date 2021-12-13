# Generated by Django 3.2.9 on 2021-12-12 12:35

from django.db import migrations, models
import django.db.models.deletion
import django.db.models.manager


class Migration(migrations.Migration):

    dependencies = [
        ('blockchain', '0006_transaction_success'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='chain',
            name='enabled',
        ),
        migrations.RemoveField(
            model_name='chain',
            name='online',
        ),
        migrations.RemoveField(
            model_name='chain',
            name='provider_url',
        ),
        migrations.RemoveField(
            model_name='chain',
            name='synced',
        ),
        migrations.CreateModel(
            name='Web3Provider',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url', models.URLField(unique=True)),
                ('enabled', models.BooleanField(default=True)),
                ('synced', models.BooleanField(default=False)),
                ('connected', models.BooleanField(default=False)),
                ('chain', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='providers', to='blockchain.chain')),
            ],
            managers=[
                ('available', django.db.models.manager.Manager()),
            ],
        ),
    ]
