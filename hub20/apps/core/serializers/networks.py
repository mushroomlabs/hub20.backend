from rest_framework import serializers

from ..models import PaymentNetwork
from .base import PolymorphicModelSerializer


class PaymentNetworkSerializer(PolymorphicModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="network-detail")

    class Meta:
        model = PaymentNetwork
        fields = read_only_fields = ("url", "name", "type", "description")


class PaymentNetworkStatusSerializer(PolymorphicModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="network-status")

    class Meta:
        model = PaymentNetwork
        fields = read_only_fields = ("url",)
