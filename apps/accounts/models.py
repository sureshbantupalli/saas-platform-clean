from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models

from apps.core.models import Tenant
from apps.authority.models import Role


# =====================================================
# Custom User Manager
# =====================================================

class UserManager(DjangoUserManager):

    def get_by_natural_key(self, email):
        return self.get(email=email)

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")

        email = self.normalize_email(email)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_platform_admin", True)

        return self.create_user(email, password, **extra_fields)


# =====================================================
# Custom User Model
# =====================================================

class User(AbstractUser):
    """
    Extends Django's AbstractUser.

    Important:
    - We keep is_staff, is_superuser, is_active from AbstractUser.
    - We DO NOT override is_staff as property.
    """

    username = None
    email = models.EmailField(unique=True)

    # -----------------------------
    # Tenant Association
    # -----------------------------
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True
    )

    # -----------------------------
    # Role Association (RBAC)
    # -----------------------------
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users"
    )

    # -----------------------------
    # Platform Admin Flag
    # -----------------------------
    is_platform_admin = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email

    # -------------------------------------------------
    # RBAC Integrity Enforcement
    # -------------------------------------------------
    def save(self, *args, **kwargs):
        """
        Platform admin:
            - No tenant required
            - No role required

        Tenant user:
            - Must have tenant
            - Must have role
            - Role must belong to same tenant
        """

        if not self.is_platform_admin:
            if not self.tenant:
                raise ValueError("Tenant user must belong to a tenant.")

            if not self.role:
                raise ValueError("Tenant user must have a role assigned.")

            if self.role.tenant_id != self.tenant_id:
                raise ValueError("Role must belong to the same tenant.")

        super().save(*args, **kwargs)

    # -------------------------------------------------
    # Permission Resolver (RBAC Engine)
    # -------------------------------------------------
    def has_permission(self, module, action):
        """
        Checks if user has given module + action permission.
        Platform admins always return True.
        """

        # Platform admin bypass
        if self.is_platform_admin or self.is_superuser:
            return True

        if not self.role:
            return False

        from apps.authority.models import RolePermission

        return RolePermission.objects.filter(
            role=self.role,
            permission_action__module=module,
            permission_action__action=action,
            is_allowed=True
        ).exists()