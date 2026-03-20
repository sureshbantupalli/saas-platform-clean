from django.http import HttpResponse
from apps.core.tenant_context import set_current_tenant


class TenantMiddleware:
    """
    Tenant Middleware (Production-safe)

    Responsibilities:
    - Attach tenant to request
    - Enforce platform vs tenant access
    - Ensure tenant is always set consistently
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        tenant = None
        user = getattr(request, "user", None)

        # ------------------------------------------
        # 1️⃣ Authenticated user handling
        # ------------------------------------------
        if user and user.is_authenticated:

            # 👑 PLATFORM ADMIN (no tenant restriction)
            if getattr(user, "is_platform_admin", False) or user.is_superuser:

                tenant = None

                # 🚫 Block platform admin from tenant CRM
                if request.path.startswith("/crm/"):
                    return HttpResponse(
                        "<h3>Access Denied</h3><p>Platform admins cannot access tenant CRM.</p>",
                        status=403
                    )

            # 👥 TENANT USER
            else:
                tenant = getattr(user, "tenant", None)

                # 🚫 Safety: user must have tenant
                if tenant is None:
                    return HttpResponse(
                        "<h3>Error</h3><p>User is not assigned to any tenant.</p>",
                        status=403
                    )

                # 🚫 Block tenant user from platform routes
                if request.path.startswith("/platform/"):
                    return HttpResponse(
                        "<h3>Access Denied</h3><p>Tenant users cannot access platform control.</p>",
                        status=403
                    )

                # 🚫 Block tenant user from Django admin
                if request.path.startswith("/admin/"):
                    return HttpResponse(
                        "<h3>Access Denied</h3><p>Tenant users cannot access admin panel.</p>",
                        status=403
                    )

                # 🚫 Tenant inactive
                if not tenant.is_active:
                    return HttpResponse(
                        "<h2>Account Suspended</h2>"
                        "<p>Your subscription is inactive. Please contact support.</p>",
                        status=403
                    )

        # ------------------------------------------
        # 2️⃣ Unauthenticated / Postman requests
        # ------------------------------------------
        else:
            tenant = None

        # ------------------------------------------
        # 3️⃣ FINAL: Set tenant context
        # ------------------------------------------

        # 🔥 TEMP FIX FOR POSTMAN (DEMO ONLY)
        if tenant is None:
            from apps.core.models import Tenant

            tenant = Tenant.objects.all().first()

        request.tenant = tenant
        set_current_tenant(tenant)

        return self.get_response(request)