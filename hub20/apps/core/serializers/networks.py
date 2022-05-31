from rest_framework import serializers

from ..models import PaymentNetwork


class PaymentNetworkSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="network-detail")

    class Meta:
        model = PaymentNetwork
        fields = read_only_fields = ("url", "name", "type", "description")
