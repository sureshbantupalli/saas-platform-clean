from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel
from apps.core.reference_types import ReferenceType


class ActivityType(models.TextChoices):
    ENROLLMENT    = "ENROLLMENT",    "Enrollment"
    PAYMENT       = "PAYMENT",       "Payment"
    DOCUMENT      = "DOCUMENT",      "Document"
    SERVICE_EVENT = "SERVICE_EVENT", "Service Event"
    NOTE          = "NOTE",          "Note"


class Activity(TenantAwareModel):
    """
    Person-facing event timeline entry. Reflective only — never a source of truth.

    References source objects via (reference_type, reference_id).
    Fetch live data from the source model; never reconstruct it from Activity rows.
    Deleting all Activity rows must leave every report and system state unchanged.
    """
    person = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="activities",
    )
    vertical = models.ForeignKey(
        "verticals.BusinessVertical",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="activities",
    )
    activity_type  = models.CharField(max_length=30, choices=ActivityType.choices, db_index=True)
    title          = models.CharField(max_length=255)
    reference_type = models.CharField(max_length=50, blank=True, choices=ReferenceType.choices)
    reference_id   = models.UUIDField(null=True, blank=True, db_index=True)
    # metadata is a display-layer convenience only.
    # Rules: no business logic may read from it; no queries may filter on it.
    # If you need to query a value, it belongs on a real model field, not here.
    metadata       = models.JSONField(default=dict, blank=True)
    created_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_activities",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["person", "-created_at"]),
            models.Index(fields=["tenant", "activity_type"]),
            # Primary timeline query: "show this person's history within a tenant"
            models.Index(fields=["tenant", "person", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.activity_type}: {self.title}"
