from django.db import models
from django.utils import timezone


class RiskLevel(models.TextChoices):
    LOW    = 'low',    'Low'
    MEDIUM = 'medium', 'Medium'
    HIGH   = 'high',   'High'


class MemberRevenueSignal(models.Model):
    """
    One row per member, updated in-place by revenue_signal_service.compute().
    Records the current risk classification and the raw inputs that drove it,
    so that dashboards and filters can read directly from DB without re-computing.
    """
    member = models.OneToOneField(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='revenue_signal',
    )
    risk_level            = models.CharField(max_length=10, choices=RiskLevel.choices, default=RiskLevel.LOW)
    risk_reason           = models.CharField(max_length=50, blank=True)
    last_payment_at       = models.DateTimeField(null=True, blank=True)
    missed_payments_count = models.PositiveIntegerField(default=0)
    updated_at            = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'revenue_member_signal'

    def __str__(self):
        return f'{self.member_id} — {self.risk_level} ({self.risk_reason})'


class NudgeLog(models.Model):
    """
    Idempotency ledger for revenue nudge events.

    Each row records one fired event.  The composite UniqueConstraint is the
    sole dedup mechanism — if NudgeLog.objects.create() raises IntegrityError,
    that event was already sent and must be silently skipped.

    IDEMPOTENCY DESIGN — do not remove the constraint or the try/except in _fire():
    IntegrityError on a duplicate create() is CONTROL FLOW, not an error.
    transaction.atomic() in _fire() isolates it in a savepoint so the outer
    transaction (e.g. a test case or a management-command batch) is not poisoned.

    NULL handling: payment_id and due_date are NULL for risk-warning events.
    nulls_distinct=False (PostgreSQL 15+) treats NULLs as equal in the index, so
    (member, "renewal_risk_warning", NULL, NULL) is truly unique per member.
    """
    member     = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='nudge_logs',
    )
    event_name = models.CharField(max_length=100)
    payment_id = models.UUIDField(null=True, blank=True)
    due_date   = models.DateField(null=True, blank=True)
    fired_at   = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'revenue_nudge_log'
        constraints = [
            models.UniqueConstraint(
                fields=['member', 'event_name', 'payment_id', 'due_date'],
                name='unique_nudge_per_event',
                nulls_distinct=False,
            )
        ]

    def __str__(self):
        return f'{self.member_id} — {self.event_name} @ {self.fired_at:%Y-%m-%d %H:%M}'
