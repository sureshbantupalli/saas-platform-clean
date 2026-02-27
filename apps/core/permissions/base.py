from apps.authority.models import RolePermission


# =========================================
# Base Permission Interface
# =========================================
class BasePermission:
    def has_permission(self, user, module, action, obj=None):
        raise NotImplementedError


# =========================================
# Database Permission Engine
# =========================================
class DatabasePermission(BasePermission):
    """
    DB-driven permission system with:
    - Role-based permission matrix
    - Scope support (ANY / OWN)
    - Per-request caching
    - Object-level enforcement
    """

    # ----------------------------------
    # Load & Cache Role Permissions
    # ----------------------------------
    def _load_permissions(self, user):
        if hasattr(user, "_permission_cache"):
            return user._permission_cache

        if not user.role or not user.tenant:
            user._permission_cache = {}
            return user._permission_cache

        role_permissions = RolePermission.base_objects.filter(
            tenant=user.tenant,
            role=user.role,
            is_allowed=True
        ).select_related("permission_action")

        permissions = {
            (rp.permission_action.module, rp.permission_action.action): rp.scope
            for rp in role_permissions
        }

        user._permission_cache = permissions
        return permissions

    # ----------------------------------
    # Basic + Object-Level Permission Check
    # ----------------------------------
    def has_permission(self, user, module, action, obj=None):
        if not user or not user.is_authenticated:
            return False

        if user.is_platform_admin:
            return True

        permissions = self._load_permissions(user)

        scope = permissions.get((module, action))

        if not scope:
            return False

        # If no object provided → module-level check only
        if obj is None:
            return True

        # Object-level enforcement
        if scope == RolePermission.SCOPE_ANY:
            return True

        if scope == RolePermission.SCOPE_OWN:
            return obj.created_by == user

        return False

    # ----------------------------------
    # Get Scope (Used by Base Service)
    # ----------------------------------
    def get_scope(self, user, module, action):
        if not user or not user.is_authenticated:
            return None

        if user.is_platform_admin:
            return RolePermission.SCOPE_ANY

        permissions = self._load_permissions(user)

        return permissions.get((module, action))