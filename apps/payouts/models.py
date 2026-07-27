from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel
from apps.core.reference_types import ReferenceType


class PayoutStatus(models.TextChoices):
    PENDING  = "pending",  "Pending"
    APPROVED = "approved", "Approved"
    PAID     = "paid",     "Paid"
    CANCELLED = "cancelled", "Cancelled"


class Payout(TenantAwareModel):
    """
    Records money paid to staff.
    rate × quantity = expected amount; actual amount may differ (disputes, adjustments).
    calculation_notes provides the human-readable trace for that derivation.
    """
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    vertical = models.ForeignKey(
        "verticals.BusinessVertical",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="payouts",
    )

    source_type = models.CharField(
        max_length=50,
        choices=ReferenceType.choices,
        default=ReferenceType.OTHER,
    )
    source_id = models.UUIDField(null=True, blank=True, db_index=True)

    # Calculation trace — makes disputes transparent
    rate               = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quantity           = models.DecimalField(max_digits=8,  decimal_places=2, null=True, blank=True)
    calculation_notes  = models.TextField(blank=True, help_text="e.g. ₹300 × 10 sessions")

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    status      = models.CharField(max_length=20, choices=PayoutStatus.choices, default=PayoutStatus.PENDING)
    notes       = models.TextField(blank=True)
    paid_at     = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="approved_payouts",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "staff"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"Payout ₹{self.amount} → {self.staff} [{self.status}]"
