from functools import wraps

from django.core.exceptions import PermissionDenied


def require_permission(code: str):
    """
    View decorator that enforces a single named permission.

    Usage:
        @require_permission("crm.view_enquiries")
        def my_view(request): ...

    Checks: user → UserRole → Role → RolePermission → Permission.code
    Platform admins and superusers bypass all checks.
    Raises 403 PermissionDenied if the user lacks the permission.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied('Authentication required.')

            from .services import RBACService
            if not RBACService.has_permission(request.user, code):
                raise PermissionDenied(f'Permission required: {code}')

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
