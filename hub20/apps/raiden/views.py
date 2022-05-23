from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from . import models, serializers


class RaidenViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.RaidenSerializer
    queryset = models.Raiden.objects.all()

    @action(detail=True, methods=["get"], serializer_class=serializers.RaidenStatusSerializer)
    def status(self, request, pk=None):
        serializer = self.get_serializer(instance=self.get_object())
        return Response(serializer.data)
