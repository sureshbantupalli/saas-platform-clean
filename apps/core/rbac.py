from functools import wraps
from django.http import JsonResponse
from core.models import RolePermission


def permission_required(permission_code):
    """
    Decorator to enforce RBAC permission checks.
    """

    def decorator(view_func):

        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):

            user = request.user

            # Superuser bypass
            if user.is_superuser:
                return view_func(request, *args, **kwargs)

            role = getattr(user, "role", None)

            if not role:
                return JsonResponse(
                    {"error": "No role assigned"},
                    status=403
                )

            allowed = RolePermission.objects.filter(
                role=role,
                permission__code=permission_code,
                is_active=True
            ).exists()

            if not allowed:
                return JsonResponse(
                    {"error": f"Permission denied: {permission_code}"},
                    status=403
                )

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator