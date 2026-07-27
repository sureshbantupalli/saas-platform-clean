"""
Nudge Service — low-level fire helper + tenant-wide scan entry point.

For member-scoped, event-driven evaluation use nudge_trigger_service.evaluate_member().
This module provides:
  • _fire()                  — atomic create-or-skip around handle_event()
  • trigger_payment_nudges() — tenant sweep (called by run_nudges management command)
  • trigger_risk_warning()   — direct risk-transition hook (called from revenue_signal_service)

IDEMPOTENCY — do not remove the try/except in _fire():
NudgeLog.objects.create() is the atomic dedup lock.  A duplicate (member,
event_name, payment_id, due_date) tuple raises IntegrityError (unique constraint
with NULLS NOT DISTINCT).  IntegrityError here is CONTROL FLOW — "already sent"
— not an error.  transaction.atomic() wraps the insert in a savepoint so the
IntegrityError stays isolated and does not poison any outer transaction (e.g.
tests or management commands that batch everything in one transaction).
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger('apps.revenue')


# ── Low-level fire helper ─────────────────────────────────────────────────────

def _fire(
    event_name: str,
    member,
    context: dict,
    tenant,
    *,
    payment_id=None,
    due_date=None,
) -> bool:
    """
    Attempt to fire event_name for member.  Returns True if fired, False if
    already sent (duplicate NudgeLog row).

    IDEMPOTENCY DESIGN — do not remove the try/except:
    NudgeLog.objects.create() is the atomic dedup lock.  Duplicate = IntegrityError
    = already sent; this is expected, not an error.  transaction.atomic() isolates
    the IntegrityError in a savepoint so it does not break the outer transaction.
    """
    from apps.revenue.models import NudgeLog
    from apps.communications.services.communication_service import handle_event

    try:
        with transaction.atomic():
            NudgeLog.objects.create(
                member=member,
                event_name=event_name,
                payment_id=payment_id,
                due_date=due_date,
            )
    except IntegrityError:
        return False  # duplicate key = already sent; this is expected, not an error

    handle_event(event_name, context, tenant)
    return True


# ── Tenant-wide payment scan (management command entry point) ─────────────────

def trigger_payment_nudges(tenant) -> dict:
    """
    Scan all members of `tenant` and evaluate payment + risk nudges for each.

    Delegates to evaluate_member() — idempotency and event routing are handled
    there.  Safe to call repeatedly; NudgeLog blocks re-firing.

    Returns a summary dict with fired counts (best-effort; counts come from
    evaluate_member which does not surface per-event counts — return zeros for
    backward compat with the management command).
    """
    from members.models import Member
    from apps.revenue.services.nudge_trigger_service import evaluate_member

    qs = Member.objects.filter(
        tenant=tenant,
        is_deleted=False,
    ).select_related('revenue_signal')

    for member in qs:
        evaluate_member(member)

    # Counts are not surfaced per-event by evaluate_member; return zeros.
    # The management command logs total run; per-event detail is in Django logs.
    return {'due_reminders': 0, 'overdue_alerts': 0}


# ── Risk-transition hook (called from revenue_signal_service) ─────────────────

def trigger_risk_warning(member, tenant) -> bool:
    """
    Fire renewal_risk_warning for a member who just transitioned to HIGH risk.

    Keyed to (member, event_name, NULL, NULL) — fires at most once per member
    until the NudgeLog row is cleared.  Use evaluate_member() for the general
    case; this function exists so revenue_signal_service can fire immediately
    on a risk transition without importing the full evaluate_member stack.
    """
    from apps.communications.events import RENEWAL_RISK_WARNING

    ctx = {
        'member_id':   str(member.pk),
        'member_name': f'{member.first_name} {member.last_name}',
        'phone':       member.phone or '',
        'email':       member.email or '',
    }

    fired = _fire(RENEWAL_RISK_WARNING, member, ctx, tenant)
    if fired:
        logger.info('nudge_fired', extra={
            'event': RENEWAL_RISK_WARNING,
            'member_id': str(member.pk),
            'tenant_id': str(tenant.pk),
        })
    return fired
