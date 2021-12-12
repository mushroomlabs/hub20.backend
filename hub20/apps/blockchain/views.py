from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from .models import Chain
from .serializers import ChainSerializer


class ChainViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = ChainSerializer
    queryset = Chain.active.all()
