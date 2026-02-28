import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import UniqueConstraint, Q
from django.db.models.functions import Lower
from apps.core.models import Branch


class Member(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="members"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_members"
    )

    is_deleted = models.BooleanField(default=False)

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)

    # 🔥 Many-to-Many Branch Relationship
    branches = models.ManyToManyField(
        Branch,
        related_name="members",
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "is_deleted"]),
            models.Index(fields=["tenant", "email"]),
            models.Index(fields=["tenant", "first_name"]),
            models.Index(fields=["tenant", "last_name"]),
        ]
        constraints = [
            UniqueConstraint(
                Lower("email"),
                "tenant",
                condition=Q(is_deleted=False) & Q(email__isnull=False),
                name="unique_active_email_per_tenant"
        )
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        # Enforce tenant consistency only (M2M validation handled in form)
        if self.pk:
            for branch in self.branches.all():
                if branch.tenant_id != self.tenant_id:
                    raise ValidationError(
                        "Member and Branch must belong to the same tenant."
                    )

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"