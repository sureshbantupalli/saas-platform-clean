from django.http import HttpResponse
from apps.core.tenant_context import set_current_tenant
from apps.core.models import Tenant


class TenantMiddleware:
    """
    Sets the current tenant in thread-local storage.

    Enforces:
    - Tenant activation
    - Strict route separation between platform and tenant users
    - Fallback header-based tenant detection (for testing)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        print("---- Tenant Middleware Hit ----")

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
            print("✅ Allowed public route")
            return self.get_response(request)

        tenant = None
        user = getattr(request, "user", None)

        # ------------------------------------------
        # 2️⃣ If user is authenticated
        # ------------------------------------------
        if user and user.is_authenticated:

            print("👤 Authenticated User Detected")

            # ===============================
            # 👑 PLATFORM ADMIN LOGIC
            # ===============================
            if getattr(user, "is_platform_admin", False) or user.is_superuser:

                print("👑 Platform Admin Access")

                set_current_tenant(None)

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

            print(f"🏢 Tenant from User: {tenant}")

            if request.path.startswith("/platform/"):
                return HttpResponse(
                    "<h3>Access Denied</h3><p>Tenant users cannot access platform control.</p>",
                    status=403
                )

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

        # ------------------------------------------
        # 4️⃣ FALLBACK — Header-based tenant (for testing)
        # ------------------------------------------
        else:
            tenant_id = request.headers.get("X-Tenant-ID")

            if tenant_id:
                try:
                    tenant = Tenant.objects.get(id=tenant_id)
                    set_current_tenant(tenant)
                    print(f"🧪 Tenant from Header: {tenant.id}")
                except Tenant.DoesNotExist:
                    set_current_tenant(None)
                    print("❌ Invalid Tenant ID (Header)")
            else:
                set_current_tenant(None)
                print("⚠️ No Tenant Found")

        return self.get_response(request)