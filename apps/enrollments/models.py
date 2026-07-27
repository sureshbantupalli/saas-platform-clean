from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TenantAwareModel
from apps.core.reference_types import ReferenceType


class Enrollment(TenantAwareModel):
    """
    Generic participation record: one person enrolled in one service within a vertical.

    Design rules:
    - Does NOT track pricing — use Payment/Membership for financial state
    - Multiple active enrollments per person are allowed (different services/verticals)
    - source_type/source_id record the referral path for analytics only; never authoritative
    - status transitions: active → paused | completed | cancelled
    """
    STATUS_ACTIVE    = "active"
    STATUS_PAUSED    = "paused"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_ACTIVE,    "Active"),
        (STATUS_PAUSED,    "Paused"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    person = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    vertical = models.ForeignKey(
        "verticals.BusinessVertical",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    # service is nullable for one valid case only: enrolling a person in a vertical
    # before a specific service has been selected or defined (e.g. a general intake
    # or a trial period). Once a service is chosen it should be set and kept.
    # DO NOT leave service null as a shortcut when the service is simply unknown —
    # create the Service record first. Null here means "vertical-level, pre-service".
    service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="enrollments",
    )

    start_date = models.DateField()
    end_date   = models.DateField(null=True, blank=True)
    status     = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True,
    )

    # Lineage — analytics only. Answers "how did this person get here?"
    # source_type is a reference to the originating record type (e.g. "consultation")
    # source_id is that record's primary key. Never used for business logic.
    source_type = models.CharField(max_length=50, blank=True, choices=ReferenceType.choices)
    source_id   = models.UUIDField(null=True, blank=True)

    notes      = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_enrollments",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Prevent re-enrolling the same person in the same service while still active.
            # Applies only when service is specified; vertical-only enrollments are unrestricted.
            models.UniqueConstraint(
                fields=["tenant", "person", "service"],
                condition=Q(status="active") & Q(service__isnull=False),
                name="unique_active_enrollment_per_person_service",
            ),
        ]
        indexes = [
            models.Index(fields=["person", "status"]),
            models.Index(fields=["tenant", "vertical", "status"]),
        ]

    def __str__(self):
        svc = self.service.name if self.service_id else "—"
        return f"{self.person} → {svc} [{self.status}]"
