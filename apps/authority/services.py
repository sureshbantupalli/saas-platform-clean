from .models import RolePermission


class RBACService:

    @staticmethod
    def has_permission(user, module, action, obj=None):
        """
        Returns (allowed: bool, scope: str | None)
        """

        if user.is_platform_admin:
            return True, "ANY"

        if not user.role:
            return False, None

        permission = RolePermission.base_objects.filter(
            role=user.role,
            permission_action__module=module,
            permission_action__action=action,
            is_allowed=True
        ).first()

        if not permission:
            return False, None

        # If no object context → just return permission
        if obj is None:
            return True, permission.scope

        # Scope enforcement
        if permission.scope == RolePermission.SCOPE_ANY:
            return True, "ANY"

        if permission.scope == RolePermission.SCOPE_OWN:
            if hasattr(obj, "created_by") and obj.created_by == user:
                return True, "OWN"
            return False, None

        return False, None