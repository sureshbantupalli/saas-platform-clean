"""
Revenue Signal Service — Phase 5.2

Computes a lightweight risk classification for a single member and persists
it to MemberRevenueSignal.  Safe to call multiple times (idempotent).

All imports are lazy (inside the function) to prevent circular dependencies
between the revenue, payments, memberships, and engagement apps.

DUE DATE DERIVATION (known limitation)
Payment has no explicit due_date field.  We use created_at.date() as a
fallback proxy — reasonable for the current billing model where payments are
created at the point they become due.

TODO: replace created_at proxy with an explicit due_date column on Payment
      once the billing model matures (separate invoices, deferred billing,
      backdated memberships).  Until then GRACE_DAYS softens the edge cases.

IDEMPOTENCY GUARANTEE
compute() writes only to revenue_member_signal (upsert, no inserts elsewhere).
It emits no signals, fires no events, and creates no log rows.  Calling it
N times with the same inputs produces the same single row.

PERFORMANCE NOTE (future)
At scale, add a composite DB index on Payment(reference_type, reference_id,
status, paid_at, created_at) and on Membership(member_id, status, is_deleted).
Not needed now; document here so the next engineer knows where to look.
"""

from django.utils import timezone

GRACE_DAYS              = 2   # days after creation before a payment is "missed"
ENGAGEMENT_STALE_DAYS   = 14  # no engagement → amplifies single missed payment to HIGH
ENGAGEMENT_VERY_STALE_DAYS = 30  # no engagement alone → MEDIUM even with no missed payments


def compute(member) -> None:
    """
    Classify `member` into a risk bucket and persist to MemberRevenueSignal.

    Raises nothing — all errors are swallowed so callers (signals, renewal
    triggers) are never broken by a revenue signal failure.
    """
    try:
        _compute(member)
    except Exception:
        import logging
        logging.getLogger('apps.revenue').exception(
            'revenue_signal_compute_failed', extra={'member_id': str(member.pk)}
        )


def _compute(member) -> None:
    from datetime import timedelta

    from django.utils.timezone import localdate

    from apps.memberships.models import Membership
    from apps.payments.models import Payment, PaymentStatus
    from apps.revenue.models import MemberRevenueSignal, RiskLevel

    today        = localdate()
    grace_cutoff = today - timedelta(days=GRACE_DAYS)

    # ── Membership IDs for this member ────────────────────────────────────────
    # Scope: exclude cancelled memberships — their unpaid payments are void,
    # not missed.  Expired memberships are included because an outstanding
    # payment on an expired membership is a genuine missed-payment signal.
    membership_ids = list(
        Membership.base_objects.filter(member=member, is_deleted=False)
        .exclude(status='cancelled')
        .values_list('id', flat=True)
    )

    # ── Missed payments ───────────────────────────────────────────────────────
    # Scope guards (important — wrong scope inflates the risk score):
    #   • reference_type='membership' only — exclude bookings, sessions, etc.
    #   • reference_id__in=membership_ids — scoped to non-cancelled memberships above
    #   • status CREATED/PENDING/FAILED — CANCELLED and REFUNDED are intentional
    #     terminal states, not missed payments; never count them
    #   • paid_at IS NULL — sanity guard; SUCCESS payments always set paid_at
    #   • created_at__date < grace_cutoff — due_date proxy (see module docstring)
    #     TODO: replace with explicit due_date field when billing model matures
    missed_payments_count = (
        Payment.base_objects.filter(
            reference_type='membership',
            reference_id__in=membership_ids,
            paid_at__isnull=True,
            status__in=[PaymentStatus.CREATED, PaymentStatus.PENDING, PaymentStatus.FAILED],
            is_deleted=False,
            created_at__date__lt=grace_cutoff,
        ).count()
    )

    # ── Last successful payment ───────────────────────────────────────────────
    last_payment_row = (
        Payment.base_objects.filter(
            reference_type='membership',
            reference_id__in=membership_ids,
            status=PaymentStatus.SUCCESS,
            is_deleted=False,
        )
        .order_by('-paid_at')
        .values('paid_at')
        .first()
    )
    last_payment_at = last_payment_row['paid_at'] if last_payment_row else None

    # ── Engagement recency (optional — gracefully absent) ─────────────────────
    # No MemberEngagementScore row → treat as maximally stale.
    # This is intentional: a member with no engagement history is unknown, and
    # unknown is treated conservatively (same as 30+ days stale).
    # Null engagement alone → MEDIUM at worst (see risk rules below).
    # It only escalates to HIGH when combined with a missed payment.
    last_engaged_at = None
    try:
        from apps.engagement.models import MemberEngagementScore
        score = MemberEngagementScore.objects.filter(member=member).first()
        if score:
            last_engaged_at = score.last_engaged_at
    except Exception:
        pass

    # ── Risk rules ────────────────────────────────────────────────────────────
    now = timezone.now()  # always UTC-aware via Django's timezone stack
    stale_cutoff      = now - timedelta(days=ENGAGEMENT_STALE_DAYS)
    very_stale_cutoff = now - timedelta(days=ENGAGEMENT_VERY_STALE_DAYS)

    # None → treated as maximally stale (conservative default)
    engagement_stale      = last_engaged_at is None or last_engaged_at < stale_cutoff
    engagement_very_stale = last_engaged_at is None or last_engaged_at < very_stale_cutoff

    if missed_payments_count >= 2:
        risk_level  = RiskLevel.HIGH
        risk_reason = 'missed_2_payments'

    elif missed_payments_count == 1 and engagement_stale:
        risk_level  = RiskLevel.HIGH
        risk_reason = 'missed_1_no_engagement'

    elif missed_payments_count == 1:
        risk_level  = RiskLevel.MEDIUM
        risk_reason = 'missed_1'

    elif engagement_very_stale:
        risk_level  = RiskLevel.MEDIUM
        risk_reason = 'no_engagement_30d'

    else:
        risk_level  = RiskLevel.LOW
        risk_reason = 'healthy'

    # ── Changed flag (Phase 5.3 hook) ────────────────────────────────────────
    # Read the existing row before overwriting so Phase 5.3 can react only to
    # genuine transitions (e.g. LOW→HIGH), not no-op re-computes.
    # No schema change required — this is a purely in-memory flag.
    prior   = MemberRevenueSignal.objects.filter(member=member).values('risk_level').first()
    changed = prior is None or prior['risk_level'] != risk_level

    # ── Persist (idempotent upsert) ───────────────────────────────────────────
    MemberRevenueSignal.objects.update_or_create(
        member=member,
        defaults={
            'risk_level':            risk_level,
            'risk_reason':           risk_reason,
            'last_payment_at':       last_payment_at,
            'missed_payments_count': missed_payments_count,
            'updated_at':            now,
        },
    )

    if changed:
        import logging
        logging.getLogger('apps.revenue').info(
            'risk_level_changed',
            extra={
                'member_id':  str(member.pk),
                'from_level': prior['risk_level'] if prior else None,
                'to_level':   risk_level,
                'reason':     risk_reason,
            },
        )
        # Nudge events (renewal_risk_warning, etc.) are NOT fired here.
        # evaluate_member() is the single brain — callers are responsible for
        # calling it after compute() so there is one decision path, not two.
