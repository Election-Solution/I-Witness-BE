from rest_framework.permissions import BasePermission
from authentication.models import AdminUser


class IsAdminUser(BasePermission):
    """Allows access to any authenticated AdminUser."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsSuperAdmin(BasePermission):
    """Restricts to superadmin role only (e.g., hard delete)."""
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == AdminUser.Role.SUPERADMIN
        )
