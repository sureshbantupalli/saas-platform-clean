from django.contrib import admin
from .models import Tenant, Branch
from .admin_base import PlatformAdminMixin


# =====================================================
# Tenant Admin (Platform Level Only)
# =====================================================

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "subdomain",
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "subdomain",
    )

    list_filter = (
        "is_active",
    )


# =====================================================
# Branch Admin (Tenant-Aware)
# =====================================================

@admin.register(Branch)
class BranchAdmin(PlatformAdminMixin):

    model = Branch

    list_display = (
        "name",
        "tenant",
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
    )

    list_filter = (
        "tenant",
        "is_active",
    )