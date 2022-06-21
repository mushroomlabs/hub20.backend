from rest_framework import serializers

from ..models import PaymentNetwork
from .base import PolymorphicModelSerializer


class PaymentNetworkSerializer(PolymorphicModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="network-detail")
    description = serializers.SerializerMethodField()

    def get_description(self, obj):
        return obj.description or obj.default_description

    class Meta:
        model = PaymentNetwork
        fields = read_only_fields = ("url", "id", "name", "type", "description")


class PaymentNetworkStatusSerializer(PolymorphicModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="network-status")

    class Meta:
        model = PaymentNetwork
        fields = read_only_fields = ("url",)
