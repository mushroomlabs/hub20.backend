from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet


class UserDataViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)


class PolymorphicModelViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    def get_serializer_class(self, *args, **kw):
        if self.action == "retrieve":
            obj = self.get_object()
            return self.serializer_class.get_subclassed_serializer(obj)

        return self.serializer_class

    def _serialize_queryset(self, qs, request):
        serializer_subclasses = self.serializer_class.__subclasses__()
        data = []
        for obj in qs:
            model = type(obj)
            serializer_class = {s.Meta.model: s for s in serializer_subclasses}.get(
                model, self.serializer_class
            )
            data.append(serializer_class(obj, context={"request": request}).data)
        return data

    def list(self, request, **kw):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self._serialize_queryset(page, request))

        return Response(self._serialize_queryset(queryset, request))
