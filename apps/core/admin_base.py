from django.contrib import admin
from apps.core.tenant_context import get_current_tenant


# =========================================================
# Platform Admin Mixin
# =========================================================
#
# PURPOSE
# -------
# Centralizes SaaS admin behavior:
#
#   ✓ Platform admins → full access
#   ✓ Tenant context → filtered access
#   ✓ Auto tenant assignment on save
#
# IMPORTANT:
# ----------
# Django Admin is used ONLY by platform admins.
# Tenant users interact via SaaS UI (not admin).
# =========================================================


class PlatformAdminMixin(admin.ModelAdmin):

    model = None  # Must be defined in child admin

    # -----------------------------------------------------
    # Queryset Control
    # -----------------------------------------------------
    def get_queryset(self, request):

        # Always start with base_objects (no auto filtering)
        qs = self.model.base_objects.all()

        user = request.user

        # -------------------------------------------------
        # 👑 Platform Admin → Full Access
        # -------------------------------------------------
        if user.is_superuser or getattr(user, "is_platform_admin", False):
            return qs

        # -------------------------------------------------
        # 🏢 Tenant Context → Filtered Access
        # -------------------------------------------------
        tenant = get_current_tenant()

        if tenant:
            return qs.filter(tenant=tenant)

        # -------------------------------------------------
        # 🚫 No Tenant → No Data
        # -------------------------------------------------
        return qs.none()

    # -----------------------------------------------------
    # Save Logic (Auto Assign Tenant)
    # -----------------------------------------------------
    def save_model(self, request, obj, form, change):

        # -------------------------------------------------
        # Auto-assign tenant if not set
        # -------------------------------------------------
        if hasattr(obj, "tenant") and not obj.tenant_id:
            tenant = get_current_tenant()
            if tenant:
                obj.tenant = tenant

        # -------------------------------------------------
        # If object has branch → enforce tenant consistency
        # -------------------------------------------------
        if hasattr(obj, "branch") and obj.branch:
            obj.tenant = obj.branch.tenant

        super().save_model(request, obj, form, change)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)

        tenant = get_current_tenant()

        # Hide tenant field when tenant context exists
        if tenant:
            fields = [f for f in fields if f != "tenant"]

        return fields