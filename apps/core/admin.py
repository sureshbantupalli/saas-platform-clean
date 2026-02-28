from django.contrib import admin
from .models import Tenant, Branch


# =====================================================
# Tenant Admin
# =====================================================

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "subdomain", "is_active", "created_at")
    search_fields = ("name", "subdomain")
    list_filter = ("is_active",)


# =====================================================
# Branch Admin
# =====================================================

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "is_active", "created_at")
    search_fields = ("name",)
    list_filter = ("tenant", "is_active")

    def get_queryset(self, request):
        if request.user.is_superuser:
            return Branch._base_manager.all()

        return super().get_queryset(request)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)

        if not request.user.is_superuser:
            fields = [f for f in fields if f != "tenant"]

        return fields

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.tenant = request.user.tenant

        super().save_model(request, obj, form, change)