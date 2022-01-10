from rest_framework import permissions


class IsTokenListOwner(permissions.IsAuthenticated):
    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated and obj.created_by == request.user
