from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from apps.core.permissions.checker import has_permission


def require_permission(module, action):
    def decorator(view_func):

        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):

            # 1️⃣ Must be authenticated
            if not request.user.is_authenticated:
                return redirect("/admin/login/")

            # 2️⃣ Superuser bypass
            if request.user.is_superuser:
                request.permission_scope = "ANY"
                return view_func(request, *args, **kwargs)

            # 3️⃣ Check permission + scope
            scope = has_permission(request.user, module, action)

            print("DEBUG - Scope from has_permission:", scope)

            if scope is None:
                return HttpResponseForbidden("You do not have permission.")

            # 🔥 Always attach scope
            request.permission_scope = scope

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator