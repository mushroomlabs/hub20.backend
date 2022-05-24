from django.db.models.query import QuerySet
from rest_framework import generics, status
from rest_framework.mixins import CreateModelMixin, DestroyModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from hub20.apps.core.views.tokens import BaseTokenViewSet

from ..serializers import (
    UserPreferencesSerializer,
    UserTokenCreatorSerializer,
    UserTokenSerializer,
)


class UserPreferencesView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserPreferencesSerializer

    def get_object(self) -> QuerySet:
        return self.request.user.preferences


class UserTokenViewSet(BaseTokenViewSet, CreateModelMixin, DestroyModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserTokenSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return UserTokenCreatorSerializer

        return self.serializer_class

    def get_queryset(self) -> QuerySet:
        qs = super().get_queryset()
        return qs.filter(userpreferences__user=self.request.user)

    def destroy(self, *args, **kw):
        token = self.get_object()
        self.request.user.preferences.tokens.remove(token)
        return Response(status.HTTP_204_NO_CONTENT)
