from django.db import models
from apps.core.models import TenantAwareModel, Tenant


# =====================================================
# Permission Action (Global)
# =====================================================

class PermissionAction(models.Model):
    """
    Defines a permission in the system.
    Example:
        module='attendance', action='create'
    """

    module = models.CharField(max_length=100)

    action = models.CharField(max_length=50)

    class Meta:
        db_table = "permission_actions"

        unique_together = ("module", "action")

        indexes = [
            models.Index(fields=["module"]),
        ]

    def __str__(self):
        return f"{self.module}:{self.action}"


# =====================================================
# Role (Tenant Scoped)
# =====================================================

class Role(TenantAwareModel):
    """
    Role within a tenant.

    Examples:
        Owner
        Manager
        Trainer
        Frontdesk
    """

    name = models.CharField(
        max_length=100
    )

    class Meta:
        db_table = "roles"

        unique_together = ("tenant", "name")

        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"


# =====================================================
# Role Permission (Tenant Scoped Matrix)
# =====================================================

class RolePermission(TenantAwareModel):

    # -------------------------------------------------
    # Permission Scope
    # -------------------------------------------------

    SCOPE_ANY = "ANY"
    SCOPE_OWN = "OWN"

    SCOPE_CHOICES = (
        (SCOPE_ANY, "Any"),
        (SCOPE_OWN, "Own"),
    )

    # -------------------------------------------------
    # Role Reference
    # -------------------------------------------------

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="permissions"
    )

    # -------------------------------------------------
    # Permission Action Reference
    # -------------------------------------------------

    permission_action = models.ForeignKey(
        PermissionAction,
        on_delete=models.CASCADE,
        related_name="role_permissions"
    )

    # -------------------------------------------------
    # Access Control
    # -------------------------------------------------

    is_allowed = models.BooleanField(
        default=True
    )

    scope = models.CharField(
        max_length=10,
        choices=SCOPE_CHOICES,
        default=SCOPE_ANY
    )

    class Meta:
        db_table = "role_permissions"

        unique_together = ("role", "permission_action")

        indexes = [
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        return f"{self.role.name} -> {self.permission_action} ({self.scope})"