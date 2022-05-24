from django.contrib.auth import get_user_model
from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework.filters import OrderingFilter
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from .. import models, serializers
from ..permissions import IsStoreOwner

User = get_user_model()


class StoreViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (AllowAny,)
    serializer_class = serializers.StoreViewerSerializer
    queryset = models.Store.objects.all()

    def get_object(self, *args, **kw):
        return get_object_or_404(models.Store, id=self.kwargs["pk"])


class UserStoreViewSet(ModelViewSet):
    permission_classes = (IsStoreOwner,)
    serializer_class = serializers.StoreEditorSerializer
    filter_backends = (OrderingFilter,)
    ordering = "id"

    def get_queryset(self) -> QuerySet:
        try:
            return self.request.user.store_set.all()
        except AttributeError:
            return models.Store.objects.none()

    def get_object(self, *args, **kw):
        store = get_object_or_404(models.Store, id=self.kwargs["pk"])
        self.check_object_permissions(self.request, store)
        return store


class CheckoutViewSet(GenericViewSet, CreateModelMixin, RetrieveModelMixin):
    permission_classes = (AllowAny,)
    serializer_class = serializers.HttpCheckoutSerializer
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self):
        return models.Checkout.objects.all()

    def get_object(self):
        return get_object_or_404(models.Checkout, id=self.kwargs["pk"])


class CheckoutRoutesViewSet(GenericViewSet, ListModelMixin, CreateModelMixin, RetrieveModelMixin):
    """
    Manages routes related to a checkout
    """

    permission_classes = (AllowAny,)
    serializer_class = serializers.CheckoutRouteSerializer
    lookup_value_regex = "[0-9a-f-]{36}"

    def get_queryset(self, *args, **kw):
        checkout_id = self.kwargs["checkout_pk"]
        return models.PaymentRoute.objects.filter(
            deposit__paymentorder__checkout=checkout_id
        ).select_subclasses()
