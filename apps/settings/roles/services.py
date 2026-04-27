from __future__ import annotations

from typing import Iterable

from .models import Permission, Role, RolePermission, UserRole


class RBACService:
    """
    Central service for the new dependency-aware RBAC system.

    Resolution order:
        user → UserRole → Role → RolePermission → Permission
    """

    # ── Permission checking ────────────────────────────────────────

    @staticmethod
    def has_permission(user, code: str) -> bool:
        """
        Return True if the user holds the named permission.
        Platform admins and superusers bypass all checks.
        """
        if getattr(user, 'is_platform_admin', False) or getattr(user, 'is_superuser', False):
            return True

        role_ids = list(
            UserRole.objects.filter(user=user).values_list('role_id', flat=True)
        )
        if not role_ids:
            return False

        return RolePermission.objects.filter(
            role_id__in=role_ids,
            permission__code=code,
        ).exists()

    @staticmethod
    def get_user_permission_codes(user) -> set[str]:
        """Return all permission codes currently granted to the user."""
        if getattr(user, 'is_platform_admin', False):
            return set(Permission.objects.values_list('code', flat=True))

        role_ids = list(
            UserRole.objects.filter(user=user).values_list('role_id', flat=True)
        )
        return set(
            RolePermission.objects.filter(role_id__in=role_ids)
            .values_list('permission__code', flat=True)
        )

    # ── Dependency resolution ──────────────────────────────────────

    @staticmethod
    def resolve_with_dependencies(permission_codes: Iterable[str]) -> list[Permission]:
        """
        Given a set of selected codes, return the full list including all
        transitive dependencies (auto-select behaviour).

        Example:
            select("crm.delete_enquiries")
            → returns [crm.view_enquiries, crm.edit_enquiries, crm.delete_enquiries]
        """
        codes = set(permission_codes)
        resolved: dict[str, Permission] = {}

        queue = list(
            Permission.objects.filter(code__in=codes).prefetch_related('depends_on')
        )
        while queue:
            perm = queue.pop()
            if perm.code not in resolved:
                resolved[perm.code] = perm
                for dep in perm.depends_on.all():
                    if dep.code not in resolved:
                        queue.append(dep)

        return list(resolved.values())

    @staticmethod
    def get_dependents_in_role(permission: Permission, role: Role) -> list[Permission]:
        """
        Return permissions currently granted to this role that depend on
        the given permission (used to warn before removal).
        """
        granted_codes = set(
            RolePermission.objects.filter(role=role)
            .values_list('permission__code', flat=True)
        )
        return list(permission.dependents.filter(code__in=granted_codes))

    # ── Role permission assignment ─────────────────────────────────

    @staticmethod
    def assign_permissions(role: Role, permission_codes: Iterable[str]) -> None:
        """
        Replace all permissions on the role with the given set,
        automatically including all required dependencies.
        """
        resolved = RBACService.resolve_with_dependencies(permission_codes)

        RolePermission.objects.filter(role=role).delete()
        if resolved:
            RolePermission.objects.bulk_create(
                [RolePermission(role=role, permission=p) for p in resolved],
                ignore_conflicts=True,
            )

    # ── User role assignment ───────────────────────────────────────

    @staticmethod
    def assign_role(user, role: Role) -> UserRole:
        obj, _ = UserRole.objects.get_or_create(user=user, role=role)
        return obj

    @staticmethod
    def remove_role(user, role: Role) -> None:
        UserRole.objects.filter(user=user, role=role).delete()

    @staticmethod
    def set_user_roles(user, roles: Iterable[Role]) -> None:
        """Replace a user's roles with exactly the given set."""
        role_ids = {r.pk for r in roles}
        UserRole.objects.filter(user=user).exclude(role_id__in=role_ids).delete()
        for role in roles:
            UserRole.objects.get_or_create(user=user, role=role)
