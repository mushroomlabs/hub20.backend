import random
from datetime import timedelta

import factory
from django.utils import timezone
from factory import fuzzy

from hub20.apps.ethereum.factories import Erc20TokenFactory, EthereumProvider, SyncedChainFactory

from .. import models

factory.Faker.add_provider(EthereumProvider)


class TokenNetworkFactory(factory.django.DjangoModelFactory):
    address = factory.Faker("ethereum_address")
    token = factory.SubFactory(Erc20TokenFactory)

    class Meta:
        model = models.TokenNetwork
        django_get_or_create = ("token",)


class RaidenFactory(factory.django.DjangoModelFactory):
    url = factory.Sequence(lambda n: "http://raiden:{0}".format(5000 + n))
    address = factory.Faker("ethereum_address")
    chain = factory.SubFactory(SyncedChainFactory)

    @factory.post_generation
    def channels(obj, create, extracted, **kw):
        if not create:
            return

        if not extracted:
            ChannelFactory(raiden=obj)
        else:
            for channel in extracted:
                obj.channels.add(channel)

    class Meta:
        model = models.Raiden
        django_get_or_create = ("chain",)


class ChannelFactory(factory.django.DjangoModelFactory):
    raiden = factory.SubFactory(RaidenFactory)
    token_network = factory.SubFactory(TokenNetworkFactory)
    partner_address = factory.Faker("ethereum_address")
    identifier = factory.Sequence(lambda n: n)
    balance = fuzzy.FuzzyDecimal(1, 100, precision=6)
    total_deposit = factory.LazyAttribute(lambda obj: obj.balance)
    total_withdraw = 0
    status = models.Channel.STATUS.opened

    class Meta:
        model = models.Channel


class PaymentEventFactory(factory.django.DjangoModelFactory):
    channel = factory.SubFactory(ChannelFactory)
    amount = factory.fuzzy.FuzzyDecimal(0, 1, precision=4)
    timestamp = factory.LazyAttribute(
        lambda obj: PaymentEventFactory.make_sequenced_timestamp(obj)
    )
    identifier = factory.Sequence(lambda n: n)
    sender_address = factory.Faker("ethereum_address")
    receiver_address = factory.Faker("ethereum_address")

    @staticmethod
    def make_sequenced_timestamp(payment_event):
        since = payment_event.channel.last_event_timestamp or timezone.now()
        return since + timedelta(microseconds=random.randint(1, int(1e8)))

    class Meta:
        model = models.Payment


__all__ = ["TokenNetworkFactory", "RaidenFactory", "ChannelFactory", "PaymentEventFactory"]
