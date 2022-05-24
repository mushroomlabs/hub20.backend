from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from ..serializers import UserSerializer

User = get_user_model()


class UserFilter(filters.FilterSet):
    search = filters.CharFilter(label="search", method="user_suggestion")

    def user_suggestion(self, queryset, name, value):
        q_username = Q(username__istartswith=value)
        q_first_name = Q(first_name__istartswith=value)
        q_last_name = Q(last_name__istartswith=value)
        q_email = Q(email__istartswith=value)
        return queryset.filter(q_username | q_first_name | q_last_name | q_email)

    class Meta:
        model = User
        fields = ("search",)


class UserViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserSerializer
    filterset_class = UserFilter
    filter_backends = (
        OrderingFilter,
        DjangoFilterBackend,
    )
    lookup_field = "username"
    ordering = "username"

    def get_queryset(self) -> QuerySet:
        return User.objects.filter(is_active=True, is_superuser=False, is_staff=False)

    def get_object(self, *args, **kw):
        return get_object_or_404(
            User,
            is_active=True,
            is_superuser=False,
            is_staff=False,
            username=self.kwargs["username"],
        )
