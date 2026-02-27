from django.contrib import admin
from .models import PermissionAction, Role, RolePermission


# -----------------------------
# PermissionAction Admin
# -----------------------------
@admin.register(PermissionAction)
class PermissionActionAdmin(admin.ModelAdmin):
    list_display = ("module", "action")
    search_fields = ("module", "action")


# -----------------------------
# Role Admin (Bypass Tenant Filter)
# -----------------------------
@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant")
    list_filter = ("tenant",)
    search_fields = ("name",)

    def get_queryset(self, request):
        return Role.base_objects.all()


# -----------------------------
# RolePermission Admin (Bypass Tenant Filter)
# -----------------------------
@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "permission_action", "is_allowed", "tenant")
    list_filter = ("tenant", "role", "permission_action", "is_allowed")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_platform_admin:
            return RolePermission.base_objects.all()
        return qs

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if request.user.is_platform_admin:
            if db_field.name == "role":
                kwargs["queryset"] = Role.base_objects.all()
            if db_field.name == "permission_action":
                kwargs["queryset"] = PermissionAction.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)