from rest_framework import permissions


class IsStoreOwnerOrAnonymousReadOnly(permissions.IsAuthenticatedOrReadOnly):
    def has_object_permission(self, request, view, obj):
        is_safe = request.method in permissions.SAFE_METHODS

        return obj.owner == request.user if request.user.is_authenticated else is_safe


class IsStoreOwner(permissions.IsAuthenticated):
    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated and obj.owner == request.user
