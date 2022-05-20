from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .models import Chain
from .serializers import ChainSerializer, ChainStatusSerializer


class ChainViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    serializer_class = ChainSerializer
    queryset = Chain.active.all()

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        chain = self.get_object()
        serializer = ChainStatusSerializer(chain, context={"request": request})
        return Response(serializer.data)
