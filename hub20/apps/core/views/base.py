from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet


class UserDataViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)


class PolymorphicModelViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    def get_serializer_class(self, *args, **kw):
        if self.action == "retrieve":
            obj = self.get_object()
            return self.serializer_class.get_subclassed_serializer(obj)

        return self.serializer_class
