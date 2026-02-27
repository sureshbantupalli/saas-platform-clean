from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.core.exceptions import PermissionDenied

from apps.authority.models import Role, PermissionAction, RolePermission
from apps.core.tenant_context import get_current_tenant


@login_required
def role_permissions_view(request):

    # --------------------------------
    # Resolve Tenant (must exist)
    # --------------------------------
    tenant = get_current_tenant()

    if not tenant:
        raise PermissionDenied("Tenant not resolved. Middleware not active.")

    # ==========================================
    # HANDLE POST (SAVE PERMISSIONS)
    # ==========================================
    if request.method == "POST":

        role_id = request.POST.get("role_id")

        if not role_id:
            return redirect("/role-permissions/")

        # Ensure role belongs to current tenant
        role = get_object_or_404(Role, id=role_id, tenant=tenant)

        with transaction.atomic():

            # Delete existing permissions for this role (tenant-safe)
            RolePermission.objects.filter(
                role=role,
                tenant=tenant
            ).delete()

            permission_actions = PermissionAction.objects.all()
            new_permissions = []

            for perm in permission_actions:

                checkbox_name = f"perm_{perm.module}_{perm.action}"
                scope_name = f"scope_{perm.module}_{perm.action}"

                if request.POST.get(checkbox_name):

                    selected_scope = request.POST.get(scope_name)

                    if selected_scope not in ["ANY", "OWN"]:
                        selected_scope = "ANY"

                    new_permissions.append(
                        RolePermission(
                            tenant=tenant,
                            role=role,
                            permission_action=perm,
                            is_allowed=True,
                            scope=selected_scope
                        )
                    )

            RolePermission.objects.bulk_create(new_permissions)

        messages.success(request, "Permissions updated successfully.")
        return redirect(f"/role-permissions/?role={role.id}")

    # ==========================================
    # HANDLE GET (DISPLAY PERMISSIONS)
    # ==========================================

    roles = Role.objects.filter(tenant=tenant)
    selected_role_id = request.GET.get("role")

    selected_role = None
    selected_permissions = {}

    if selected_role_id:
        selected_role = Role.objects.filter(
            id=selected_role_id,
            tenant=tenant
        ).first()

        if selected_role:
            role_permissions = RolePermission.objects.filter(
                role=selected_role,
                tenant=tenant,
                is_allowed=True
            )

            for rp in role_permissions:
                selected_permissions[rp.permission_action_id] = rp.scope

    permission_actions = PermissionAction.objects.all()

    context = {
        "roles": roles,
        "permission_actions": permission_actions,
        "selected_role": selected_role,
        "selected_permissions": selected_permissions,
    }

    return render(request, "authority/role_permissions.html", context)