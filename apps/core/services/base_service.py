from django.core.exceptions import PermissionDenied
from apps.core.permissions.base import DatabasePermission
    from apps.authority.models import RolePermission


class BaseTenantService:
    """
    Generic reusable service base class

    Handles:
    - Module-level permission check
    - Scope enforcement (OWN / ANY)
    - Tenant filtering
    """

    permission_engine = DatabasePermission()

    def __init__(self, module_key, model_class):
        self.module_key = module_key
        self.model_class = model_class

    # ----------------------------------
    # Permission Check (Module-Level)
    # ----------------------------------
    def check(self, user, action):
        if not self.permission_engine.has_permission(
            user,
            self.module_key,
            action
        ):
            raise PermissionDenied(
                f"You do not have permission to {action} {self.module_key}."
            )

    # ----------------------------------
    # Get Scoped Queryset (List-Level)
    # ----------------------------------
    def get_queryset(self, user, action="view"):
        """
        Returns queryset filtered by:
        - Tenant isolation
        - Scope enforcement (OWN / ANY)
        """

        # Always start from tenant-scoped manager
        base_qs = self.model_class.scoped.for_user(user)

        scope = self.permission_engine.get_scope(
            user,
            self.module_key,
            action
        )

        # If no scope → no access
        if not scope:
            raise PermissionDenied(
                f"You do not have permission to {action} {self.module_key}."
            )

        # Platform admin sees everything
        if user.is_platform_admin:
            return base_qs

        # OWN scope → filter by created_by
        if scope == RolePermission.SCOPE_OWN:
            return base_qs.filter(created_by=user)

        # ANY scope → return full tenant queryset
        return base_qs

    # ----------------------------------
    # Get Single Object with Scope
    # ----------------------------------
    def get_object(self, user, object_id, action):
        """
        Fetch single object respecting:
        - Tenant isolation
        - Scope enforcement
        """

        # Permission check first
        self.check(user, action)

        obj = self.get_queryset(user, action=action).filter(
            id=object_id
        ).first()

        if not obj:
            raise PermissionDenied(
                "Record not found or access denied."
            )

        return obj