from django.http import HttpResponse
from apps.core.tenant_context import set_current_tenant


class TenantMiddleware:
    """
    Resolves tenant context from the authenticated user and enforces
    platform-vs-tenant access rules on every request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        tenant = None
        user = getattr(request, "user", None)

        if user and user.is_authenticated:

            if getattr(user, "is_platform_admin", False) or user.is_superuser:
                # Platform admins have no tenant context; block them from tenant CRM.
                if request.path.startswith("/crm/"):
                    return HttpResponse(
                        "<h3>Access Denied</h3><p>Platform admins cannot access tenant CRM.</p>",
                        status=403
                    )

            else:
                tenant = getattr(user, "tenant", None)

                if tenant is None:
                    return HttpResponse(
                        "<h3>Error</h3><p>User is not assigned to any tenant.</p>",
                        status=403
                    )

                if request.path.startswith("/platform/"):
                    return HttpResponse(
                        "<h3>Access Denied</h3><p>Tenant users cannot access platform control.</p>",
                        status=403
                    )

                if request.path.startswith("/admin/") and not user.is_superuser:
                    return HttpResponse(
                        "<h3>Access Denied</h3><p>Tenant users cannot access admin panel.</p>",
                        status=403
                    )

                if not tenant.is_active:
                    return HttpResponse(
                        "<h2>Account Suspended</h2>"
                        "<p>Your subscription is inactive. Please contact support.</p>",
                        status=403
                    )

        request.tenant = tenant
        set_current_tenant(tenant)

        return self.get_response(request)