import uuid
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils.text import slugify
from .tenant_context import get_current_tenant


# =====================================================
# Base Model (UUID + Timestamps)
# =====================================================

class BaseModel(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ✅ Soft Delete Support
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True


# =====================================================
# Tenant Model
# =====================================================

class Tenant(BaseModel):

    name = models.CharField(
        max_length=255,
        unique=True
    )

    subdomain = models.SlugField(
        max_length=100,
        unique=True
    )

    # Used by billing / subscription system later
    is_active = models.BooleanField(
        default=True
    )

    grace_days = models.PositiveIntegerField(
        default=0,
        help_text="Number of grace days after membership final end date"
    )

    class Meta:
        db_table = "tenants"

        indexes = [
            models.Index(fields=["subdomain"]),
        ]

    def save(self, *args, **kwargs):

        # Detect new tenant creation
        is_new = not Tenant.objects.filter(pk=self.pk).exists()

        # Auto-generate subdomain if not provided
        if not self.subdomain:
            self.subdomain = slugify(self.name)

        super().save(*args, **kwargs)

        # Automatically create CRM stages
        if is_new:
            self.create_default_stages()

    # =====================================================
    # Default CRM Pipeline Creation
    # =====================================================

    def create_default_stages(self):

        from crm.models import LeadStage

        default_stages = [
            {"name": "New", "order": 1},
            {"name": "Contacted", "order": 2},
            {"name": "Demo Done", "order": 3},
            {"name": "Converted", "order": 4, "is_conversion_stage": True},
            {"name": "Lost", "order": 5, "is_loss_stage": True},
        ]

        for stage in default_stages:
            LeadStage.objects.get_or_create(
                tenant=self,
                name=stage["name"],
                defaults={
                    "order": stage["order"],
                    "is_conversion_stage": stage.get("is_conversion_stage", False),
                    "is_loss_stage": stage.get("is_loss_stage", False),
                }
            )

    def __str__(self):
        return self.name


# =====================================================
# Tenant Scoped QuerySet
# =====================================================

class TenantScopedQuerySet(models.QuerySet):

    def for_user(self, user):

        if user.is_platform_admin:
            return self

        if not user.tenant:
            raise PermissionDenied(
                "User does not belong to any tenant."
            )

        return self.filter(tenant=user.tenant)

    # Hide soft deleted records
    def active(self):
        return self.filter(is_deleted=False)


# =====================================================
# Tenant Scoped Manager
# =====================================================

class TenantScopedManager(models.Manager):

    def get_queryset(self):

        queryset = TenantScopedQuerySet(
            self.model,
            using=self._db
        )

        current_tenant = get_current_tenant()

        # Auto apply tenant filter if context exists
        if current_tenant is not None:
            return queryset.filter(
                tenant=current_tenant,
                is_deleted=False
            )

        return queryset.none()

    def for_user(self, user):

        return TenantScopedQuerySet(
            self.model,
            using=self._db
        ).for_user(user).filter(is_deleted=False)


# =====================================================
# Tenant Aware Base Model
# =====================================================

class TenantAwareModel(BaseModel):

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="%(class)ss"
    )

    # Default manager (safe for admin / M2M validation)
    base_objects = models.Manager()
    objects = base_objects

    # Tenant-scoped manager used explicitly in code
    scoped = TenantScopedManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):

        # -------------------------------------------------
        # Assign tenant automatically for new records
        # -------------------------------------------------
        if not self.pk:

            if self.tenant_id is None:

                current_tenant = get_current_tenant()

                if current_tenant is None:
                    raise ValueError(
                        "Tenant must be explicitly set or available in context."
                    )

                self.tenant = current_tenant

        else:

            original = self.__class__.base_objects.filter(
                pk=self.pk
            ).first()

            if original and original.tenant_id != self.tenant_id:
                raise ValueError(
                    "Tenant cannot be changed once set."
                )

        super().save(*args, **kwargs)


# =====================================================
# Branch Model
# =====================================================

class Branch(TenantAwareModel):

    name = models.CharField(
        max_length=150
    )

    address = models.TextField(
        blank=True
    )

    phone = models.CharField(
        max_length=20,
        blank=True
    )

    email = models.EmailField(
        blank=True
    )

    is_active = models.BooleanField(
        default=True
    )

    class Meta:
        db_table = "branches"

        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="unique_branch_name_per_tenant"
            )
        ]

    def __str__(self):
        return self.name