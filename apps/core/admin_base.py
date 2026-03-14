from django.contrib import admin


# =========================================================
# Platform Admin Mixin
# =========================================================
#
# PURPOSE
# -------
# This mixin centralizes common SaaS admin behavior used across
# multiple Django admin classes.
#
# Why this file exists:
# - Our models use TenantScopedQuerySet which automatically filters
#   data by tenant.
# - Django Admin must bypass that filtering for platform admins.
#
# This mixin ensures:
#   ✓ Platform admins see ALL tenants
#   ✓ Tenant users see only their tenant
#   ✓ Tenant is automatically assigned when saving objects
#
# Usage:
#
#     from apps.core.admin_base import PlatformAdminMixin
#
#     @admin.register(SomeModel)
#     class SomeModelAdmin(PlatformAdminMixin):
#         model = SomeModel
#
# This prevents duplicating tenant logic in every admin file.
#
# IMPORTANT:
# ----------
# Tenant staff DO NOT access Django Admin in our SaaS architecture.
# Django Admin is strictly used by PLATFORM administrators.
#
# Tenant users interact with the system through the SaaS UI.
#
# =========================================================


class PlatformAdminMixin(admin.ModelAdmin):

    # Child admin classes must define their model
    model = None

    # -----------------------------------------------------
    # Bypass TenantScopedQuerySet for Admin
    # -----------------------------------------------------

    def get_queryset(self, request):

        # Use base_objects to bypass tenant filtering
        qs = self.model.base_objects.all()

        user = request.user

        # Platform admins can see everything
        if user.is_superuser or getattr(user, "is_platform_admin", False):
            return qs

        # Tenant users see only their tenant data
        if user.tenant:
            return qs.filter(tenant=user.tenant)

        return qs

    # -----------------------------------------------------
    # Auto Assign Tenant
    # -----------------------------------------------------

    def save_model(self, request, obj, form, change):

        # If model has branch → derive tenant automatically
        if hasattr(obj, "branch") and obj.branch:
            obj.tenant = obj.branch.tenant

        super().save_model(request, obj, form, change)