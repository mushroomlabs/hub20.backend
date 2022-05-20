from rest_framework import permissions


class IsTokenListOwner(permissions.IsAuthenticated):
    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated and obj.user == request.user


class IsAdminOrReadOnly(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        if request.method.upper() in permissions.SAFE_METHODS:
            return True

        return request.user.is_staff
