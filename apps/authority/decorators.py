from functools import wraps
from django.core.exceptions import PermissionDenied
from .services import RBACService


def require_permission(module, action, get_object_func=None):
    """
    Decorator to enforce RBAC permission on Django views.
    get_object_func(request, *args, **kwargs) → returns object
    """

    def decorator(view_func):

        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):

            user = request.user

            if not user.is_authenticated:
                raise PermissionDenied("Authentication required.")

            obj = None
            if get_object_func:
                obj = get_object_func(request, *args, **kwargs)

            allowed, scope = RBACService.has_permission(
                user, module, action, obj=obj
            )

            if not allowed:
                raise PermissionDenied(
                    f"Permission denied: {module}:{action}"
                )

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator