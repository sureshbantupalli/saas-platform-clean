from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel


class Permission(models.Model):
    """
    Global permission catalogue entry. Not tenant-scoped.
    code format: "{module}.{action}"  e.g. "crm.view_enquiries"
    """
    code        = models.CharField(max_length=100, unique=True)
    label       = models.CharField(max_length=150)
    module      = models.CharField(max_length=50, db_index=True)
    description = models.TextField(blank=True)
    depends_on  = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=False,
        related_name='dependents',
        help_text='Permissions that must be granted before this one can be assigned.',
    )

    class Meta:
        db_table = 'settings_permissions'
        ordering = ['module', 'code']

    def __str__(self):
        return self.code

    def all_dependencies(self):
        """Return the full transitive closure of this permission's dependencies."""
        visited_ids = set()
        queue = list(self.depends_on.all())
        while queue:
            perm = queue.pop()
            if perm.pk not in visited_ids:
                visited_ids.add(perm.pk)
                queue.extend(perm.depends_on.all())
        return Permission.objects.filter(pk__in=visited_ids)


class Role(TenantAwareModel):
    """Tenant-scoped role definition."""

    # Override related_name to avoid clash with authority.Role (both inherit TenantAwareModel)
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='settings_roles',
    )

    name       = models.CharField(max_length=100)
    is_default = models.BooleanField(
        default=False,
        help_text='Automatically assigned to new users in this tenant.',
    )

    class Meta:
        db_table        = 'settings_roles'
        unique_together = [('tenant', 'name')]
        ordering        = ['name']

    def __str__(self):
        return f'{self.name} ({self.tenant.name})'

    def permission_count(self):
        return self.role_permissions.count()


class RolePermission(models.Model):
    """Maps a role to a single permission."""
    role       = models.ForeignKey(Role,       on_delete=models.CASCADE, related_name='role_permissions')
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='role_permissions')

    class Meta:
        db_table        = 'settings_role_permissions'
        unique_together = [('role', 'permission')]

    def __str__(self):
        return f'{self.role.name} → {self.permission.code}'


class UserRole(models.Model):
    """Assigns a user to one or more roles (replaces single role FK)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_roles',
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name='user_roles',
    )

    class Meta:
        db_table        = 'settings_user_roles'
        unique_together = [('user', 'role')]

    def __str__(self):
        return f'{self.user.email} → {self.role.name}'
