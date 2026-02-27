from django.db import transaction

from apps.core.models import Tenant
from apps.authority.models import Role, PermissionAction, RolePermission
from apps.core.permissions.definition_registry import PERMISSION_DEFINITIONS


class TenantProvisionService:
    """
    Handles complete tenant provisioning process.

    Responsibilities:
    - Create Tenant
    - Create default Roles
    - Assign baseline RolePermissions
    """

    DEFAULT_ROLES = ["Admin", "Manager", "Staff", "Viewer"]

    BASELINE_RULES = {
        "Admin": {
            "actions": "ALL",
            "scope": RolePermission.SCOPE_ANY,
        },
        "Manager": {
            "actions": "ALL",
            "scope": RolePermission.SCOPE_ANY,
        },
        "Staff": {
            "actions": ["view", "update"],
            "scope": RolePermission.SCOPE_OWN,
        },
        "Viewer": {
            "actions": ["view"],
            "scope": RolePermission.SCOPE_ANY,
        },
    }

    @transaction.atomic
    def provision_tenant(self, **tenant_data):
        # 1️⃣ Create Tenant
        tenant = Tenant.objects.create(**tenant_data)

        # 2️⃣ Create Roles
        roles = {}
        for role_name in self.DEFAULT_ROLES:
            role = Role.objects.create(
                tenant=tenant,
                name=role_name
            )
            roles[role_name] = role

        # 3️⃣ Assign Baseline Permissions
        self._assign_baseline_permissions(tenant, roles)

        return tenant

    def _assign_baseline_permissions(self, tenant, roles: dict):
        """
        Creates RolePermission entries based on baseline rules.
        Idempotent and safe.
        """

        # Fetch all PermissionActions once
        permission_actions = PermissionAction.objects.all()

        for role_name, role in roles.items():
            rule = self.BASELINE_RULES.get(role_name)

            if not rule:
                continue

            allowed_actions = rule["actions"]
            scope = rule["scope"]

            for permission in permission_actions:
                # Decide whether this permission applies
                if allowed_actions != "ALL":
                    if permission.action not in allowed_actions:
                        continue

                RolePermission.objects.get_or_create(
                    tenant=tenant,
                    role=role,
                    permission_action=permission,
                    defaults={
                        "is_allowed": True,
                        "scope": scope,
                    }
                )