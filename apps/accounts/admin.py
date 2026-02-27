from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from apps.authority.models import Role
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User

    list_display = (
        "email",
        "tenant",
        "role",
        "is_platform_admin",
        "is_staff",
        "is_active",
    )

    list_filter = (
        "tenant",
        "role",
        "is_platform_admin",
        "is_staff",
        "is_active",
    )

    ordering = ("email",)
    search_fields = ("email",)

    # 🔥 IMPORTANT PART
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "role":
            # platform admin can see all roles
            if request.user.is_platform_admin:
                kwargs["queryset"] = Role.base_objects.all()
            else:
                # normal user sees roles only in their tenant
                kwargs["queryset"] = Role.base_objects.filter(
                    tenant=request.user.tenant
                )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    fieldsets = (
        (None, {"fields": ("email", "password")}),

        (
            "Tenant & Role",
            {
                "fields": (
                    "tenant",
                    "role",
                )
            },
        ),

        (
            "System Permissions",
            {
                "fields": (
                    "is_platform_admin",
                    "is_staff",
                    "is_active",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),

        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "tenant",
                    "role",
                    "is_platform_admin",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )

    filter_horizontal = ("groups", "user_permissions")