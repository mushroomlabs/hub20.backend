from rest_framework import serializers

from ..models import PaymentNetwork


class PaymentNetworkSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentNetwork
        fields = read_only_fields = ("name", "type")
