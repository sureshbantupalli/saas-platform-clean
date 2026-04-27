from django.contrib import admin

from .models import Permission, Role, RolePermission, UserRole


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display  = ('code', 'label', 'module')
    list_filter   = ('module',)
    search_fields = ('code', 'label')
    filter_horizontal = ('depends_on',)
    ordering = ('module', 'code')


class RolePermissionInline(admin.TabularInline):
    model      = RolePermission
    extra      = 0
    raw_id_fields = ('permission',)


class UserRoleInline(admin.TabularInline):
    model = UserRole
    extra = 0
    raw_id_fields = ('user',)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display  = ('name', 'tenant', 'is_default', 'permission_count')
    list_filter   = ('tenant', 'is_default')
    search_fields = ('name',)
    inlines       = [RolePermissionInline, UserRoleInline]

    def permission_count(self, obj):
        return obj.role_permissions.count()
    permission_count.short_description = 'Permissions'
