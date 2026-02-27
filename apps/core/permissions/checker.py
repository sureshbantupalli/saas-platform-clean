from apps.authority.models import RolePermission, PermissionAction
from apps.core.tenant_context import get_current_tenant


def has_permission(user, module, action):

    # 1️⃣ Must be authenticated
    if not user.is_authenticated:
        return None

    # 2️⃣ Platform admin bypass (optional safety layer)
    if getattr(user, "is_platform_admin", False):
        return "ANY"

    # 3️⃣ Tenant must exist
    tenant = get_current_tenant()
    if not tenant:
        return None

    # 4️⃣ User must have role
    if not user.role:
        return None

    # 5️⃣ Get permission action
    try:
        permission_action = PermissionAction.objects.get(
            module=module,
            action=action
        )
    except PermissionAction.DoesNotExist:
        return None

    # 6️⃣ Find role permission for this tenant
    role_permission = RolePermission.objects.filter(
        role=user.role,
        permission_action=permission_action,
        tenant=tenant,
        is_allowed=True
    ).first()

    if not role_permission:
        return None

    # 7️⃣ Return scope (ANY or OWN)
    return role_permission.scope