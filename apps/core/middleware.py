from django.http import HttpResponse
from django.shortcuts import redirect
from apps.core.tenant_context import set_current_tenant

class TenantMiddleware:
    """
    Sets the current tenant in thread-local storage.

    ```
    Enforces:
    - Tenant activation
    - Strict route separation between platform and tenant users
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # ------------------------------------------
        # 1️⃣ Allow public/auth routes always
        # ------------------------------------------
        allowed_paths = [
            "/login/",
            "/logout/",
            "/admin/login/",
            "/admin/logout/",
        ]

        if request.path in allowed_paths:
            return self.get_response(request)

        tenant = None
        user = getattr(request, "user", None)

        # ------------------------------------------
        # 2️⃣ If user is authenticated
        # ------------------------------------------
        if user and user.is_authenticated:

                # ===============================
                # 👑 PLATFORM ADMIN LOGIC
            # ===============================
            if getattr(user, "is_platform_admin", False) or user.is_superuser:

                set_current_tenant(None)

                # Block platform admin from CRM
                if request.path.startswith("/crm/"):
                    return HttpResponse(
                        "<h3>Access Denied</h3><p>Platform admins cannot access tenant CRM.</p>",
                        status=403
                    )

                return self.get_response(request)

            # ===============================
            # 👥 TENANT USER LOGIC
            # ===============================
            tenant = getattr(user, "tenant", None)
            set_current_tenant(tenant)

            # Block tenant user from platform routes
            if request.path.startswith("/platform/"):
                return HttpResponse(
                    "<h3>Access Denied</h3><p>Tenant users cannot access platform control.</p>",
                    status=403
                )

            # Block tenant user from Django admin
            if request.path.startswith("/admin/"):
                return HttpResponse(
                    "<h3>Access Denied</h3><p>Tenant users cannot access admin panel.</p>",
                    status=403
                )

            # ------------------------------------------
            # 3️⃣ Enforce tenant activation
            # ------------------------------------------
            if tenant and not tenant.is_active:
                return HttpResponse(
                    """
                    <h2>Account Suspended</h2>
                    <p>Your subscription is inactive. Please contact support.</p>
                    """,
                    status=403
                )

        return self.get_response(request)
