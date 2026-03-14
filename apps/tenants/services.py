from django.contrib.auth import get_user_model

from apps.core.models import Tenant
from apps.authority.models import Role


User = get_user_model()


class TenantService:

    DEFAULT_ROLES = [
        "Owner",
        "Manager",
        "Trainer",
        "Frontdesk",
    ]

    @staticmethod
    def create_tenant(name, subdomain, admin_email, password):

        # ---------------------------------
        # Create Tenant
        # ---------------------------------
        tenant = Tenant.objects.create(
            name=name,
            subdomain=subdomain,
            is_active=True,
            grace_days=0
        )

        # ---------------------------------
        # Create Default Roles
        # ---------------------------------
        roles = {}

        for role_name in TenantService.DEFAULT_ROLES:

            role, created = Role.objects.get_or_create(
                tenant=tenant,
                name=role_name
            )

            roles[role_name] = role

        # ---------------------------------
        # Assign Default Permissions
        # ---------------------------------
        from apps.authority.models import PermissionAction, RolePermission

        permissions = PermissionAction.objects.all()

        for permission in permissions:

            # Owner → full access
            RolePermission.objects.get_or_create(
                tenant=tenant,
                role=roles["Owner"],
                permission_action=permission,
                defaults={"is_allowed": True}
            )

            # Manager → operational modules
            if permission.module in ["CORE", "MEMBERS", "CRM"]:
                RolePermission.objects.get_or_create(
                    tenant=tenant,
                    role=roles["Manager"],
                    permission_action=permission,
                    defaults={"is_allowed": True}
                )

            # Trainer → member viewing
            if permission.module in ["MEMBERS"]:
                RolePermission.objects.get_or_create(
                    tenant=tenant,
                    role=roles["Trainer"],
                    permission_action=permission,
                    defaults={"is_allowed": True}
                )

            # Frontdesk → CRM + members
            if permission.module in ["CRM", "MEMBERS"]:
                RolePermission.objects.get_or_create(
                    tenant=tenant,
                    role=roles["Frontdesk"],
                    permission_action=permission,
                    defaults={"is_allowed": True}
                )
        
        # ---------------------------------
        # Create Owner User
        # ---------------------------------
        admin_user = User.objects.create_user(
            email=admin_email,
            password=password,
            tenant=tenant,
            role=roles["Owner"],
            is_active=True
        )

        return tenant