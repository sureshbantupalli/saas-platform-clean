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

    is_active = models.BooleanField(
        default=True
    )

    grace_days = models.PositiveIntegerField(
        default=0,
        help_text="Number of grace days after membership final end date"
    )

    is_platform = models.BooleanField(
        default=False,
        help_text=(
            "Marks the internal ANJASI tenant used for platform-level "
            "communication (onboarding, invoices, service notices). It has no "
            "members and must be excluded from tenant-facing batch jobs."
        ),
    )

    class Meta:
        db_table = "tenants"

        indexes = [
            models.Index(fields=["subdomain"]),
        ]

        constraints = [
            # There can be only one platform tenant. Two would make
            # get_platform_tenant() ambiguous and silently split platform
            # templates across them.
            models.UniqueConstraint(
                fields=["is_platform"],
                condition=models.Q(is_platform=True),
                name="only_one_platform_tenant",
            ),
        ]

    def save(self, *args, **kwargs):

        is_new = self._state.adding  # ✅ better than DB query

        # ---------------------------------------------
        # Generate unique subdomain safely
        # ---------------------------------------------
        if not self.subdomain:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            while Tenant.objects.filter(subdomain=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.subdomain = slug

        super().save(*args, **kwargs)

        # ---------------------------------------------
        # Create default CRM stages (only once)
        # ---------------------------------------------
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

    def __repr__(self):
        return f"<Tenant {self.id} - {self.name}>"

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

from apps.core.managers.tenant_manager import TenantManager

class TenantAwareModel(BaseModel):
    """Base for every tenant-owned model. Read the manager notes before querying.

    Three managers are exposed and picking the wrong one is the single most
    common source of confusing bugs in this codebase:

    ``objects``       TenantManager — filters to ``get_current_tenant()``.
                      **Returns .none() when no tenant context is set.** The
                      context is populated by middleware during a request, so
                      it is absent in management commands, cron jobs, the
                      shell, migrations and most tests. In those places
                      ``Model.objects.all()`` silently yields nothing — no
                      error, no warning, just an empty queryset that reads as
                      "no data" rather than "wrong manager".

    ``base_objects``  Plain Manager — no filtering at all. Use this whenever
                      you are outside a request and pass ``tenant=`` yourself,
                      e.g. ``TriggerRule.base_objects.filter(tenant=tenant)``
                      in communication_service.handle_event(). Also the right
                      choice for cross-tenant admin and batch work.

    ``scoped``        TenantScopedManager — like ``objects`` but also excludes
                      soft-deleted rows, and offers ``.for_user(user)`` which
                      lets a platform admin see everything.

    Rule of thumb: inside a request use ``objects``; anywhere else use
    ``base_objects`` with an explicit ``tenant=`` filter.
    """

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="%(class)ss"
    )

    # Unfiltered. Safe outside a request — but YOU must pass tenant=.
    base_objects = models.Manager()

    # Default. Auto-filters to the current tenant; .none() without context.
    objects = TenantManager()

    # Tenant-filtered + soft-delete aware, plus .for_user().
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
        if self.tenant:
            return f"{self.name} ({self.tenant.name})"
        return self.name