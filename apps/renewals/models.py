"""
RenewalTriggerLog — idempotency shield for the renewal engine.

Records every (membership, trigger_type, expiry_date) triple that has been
actioned. The triple unique constraint ensures that for a given membership at
a given expiry date, each trigger stage fires exactly once.

When a membership renews (new end_date / final_end_date), the expiry_date
component changes, so a fresh set of triggers becomes eligible — no manual
cleanup required.
"""
from django.db import models
from django.utils import timezone

from apps.core.models import TenantAwareModel


class TriggerType(models.TextChoices):
    EXPIRING_7D = 'expiring_7d', 'Expiring in 7 days'
    EXPIRING_3D = 'expiring_3d', 'Expiring in 3 days'
    EXPIRING_1D = 'expiring_1d', 'Expiring in 1 day'
    EXPIRED     = 'expired',     'Expired (recovery)'


class RenewalTriggerLog(TenantAwareModel):
    """
    One record per (membership, trigger_type, expiry_date).

    The trigger layer (Phase 2) creates this record after calling handle_event().
    The detection layer reads it to skip already-actioned memberships.
    """
    membership = models.ForeignKey(
        'memberships.Membership',
        on_delete=models.CASCADE,
        related_name='renewal_logs',
    )
    trigger_type = models.CharField(
        max_length=20,
        choices=TriggerType.choices,
        db_index=True,
    )
    # Snapshot of final_end_date at trigger time — key for renewal cycle isolation.
    # When membership renews, this date changes → old logs no longer block new triggers.
    expiry_date  = models.DateField()
    triggered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'renewals_trigger_log'
        unique_together = [('membership', 'trigger_type', 'expiry_date')]
        indexes = [
            models.Index(fields=['membership', 'trigger_type', 'expiry_date']),
        ]

    def __str__(self):
        return f'{self.trigger_type} / {self.membership_id} / {self.expiry_date}'
