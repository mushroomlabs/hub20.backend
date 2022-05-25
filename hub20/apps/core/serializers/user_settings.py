from rest_framework import serializers

from ..models import BaseToken, UserPreferences
from .tokens import HyperlinkedRelatedTokenField


class UserPreferencesSerializer(serializers.ModelSerializer):
    tokens = HyperlinkedRelatedTokenField(
        view_name="token-detail",
        queryset=BaseToken.tradeable.all(),
        many=True,
    )

    class Meta:
        model = UserPreferences
        fields = ("tokens",)
