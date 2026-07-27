"""
Nudge Trigger Service — central evaluation engine.

evaluate_member(member) is the single entry point for revenue nudge decisions.
It is stateless, condition-driven, and safe to call any number of times —
NudgeLog's unique constraint guarantees exactly-once delivery per condition.

Mental model:
    evaluate_member() = stateless decision engine
    NudgeLog          = memory (already-fired ledger)
    handle_event()    = execution pipeline (retry + escalation + learning)

WHEN TO CALL
    • After PaymentService.mark_payment_success()
    • After compute() (revenue signal update)
    • From run_nudges management command (full-tenant sweep)
    All calls are safe due to idempotency.

DUE DATE DERIVATION
    Payment has no explicit due_date field.  We use Membership.end_date as the
    proxy — semantically correct: the fee is due when the membership expires.

    TODO: if an explicit due_date is added to Payment, prefer that here.
"""

import logging

from django.utils import timezone

from apps.communications.events import (
    PAYMENT_DUE_REMINDER,
    PAYMENT_OVERDUE_ALERT,
    RENEWAL_RISK_WARNING,
)

logger = logging.getLogger('apps.revenue')

DUE_REMINDER_DAYS = 2


def evaluate_member(member) -> None:
    """
    Evaluate and fire pending nudge events for a single member.
    Swallows all exceptions — nudge failures must never break the caller.
    """
    try:
        _evaluate(member)
    except Exception:
        logger.exception(
            'nudge_evaluate_failed',
            extra={'member_id': str(member.pk)},
        )


def _evaluate(member) -> None:
    from apps.memberships.models import Membership
    from apps.payments.models import Payment, PaymentStatus
    from apps.revenue.models import MemberRevenueSignal, RiskLevel
    from apps.revenue.services.nudge_service import _fire

    today = timezone.now().date()

    # ── 1. Payment-based triggers ─────────────────────────────────────────────

    membership_ids = list(
        Membership.base_objects.filter(member=member, is_deleted=False)
        .exclude(status='cancelled')
        .values_list('id', flat=True)
    )

    if membership_ids:
        memberships_by_id = {
            m.id: m
            for m in Membership.base_objects.filter(pk__in=membership_ids)
        }

        unpaid = Payment.base_objects.filter(
            reference_type='membership',
            reference_id__in=membership_ids,
            paid_at__isnull=True,
            status__in=[PaymentStatus.CREATED, PaymentStatus.PENDING, PaymentStatus.FAILED],
            is_deleted=False,
        )

        for payment in unpaid:
            membership = memberships_by_id.get(payment.reference_id)
            if not membership or not membership.end_date:
                continue

            due_date     = membership.end_date
            days_to_due  = (due_date - today).days

            context = {
                'member_id':  str(member.pk),
                'member_name': f'{member.first_name} {member.last_name}',
                'phone':       member.phone or '',
                'email':       member.email or '',
                'payment_id':  str(payment.pk),
                'due_date':    str(due_date),
                'amount':      str(payment.amount),
            }

            if days_to_due == DUE_REMINDER_DAYS:
                fired = _fire(
                    PAYMENT_DUE_REMINDER, member, context, member.tenant,
                    payment_id=payment.pk, due_date=due_date,
                )
                if fired:
                    logger.info('nudge_fired', extra={
                        'event': PAYMENT_DUE_REMINDER,
                        'member_id': str(member.pk),
                        'payment_id': str(payment.pk),
                    })

            if days_to_due < 0:
                # OPTION A (current): fire once per payment ever.
                # NudgeLog key = (member, event, payment_id, due_date) — never repeats.
                #
                # OPTION B (future UX): repeat every N days while still unpaid.
                # Implementation: add a `cycle_key` date field to NudgeLog keyed to
                # floor(today / REPEAT_INTERVAL), or delete+recreate the NudgeLog row
                # after N days.  Requires a schema change — defer until needed.
                context['days_overdue'] = str(abs(days_to_due))
                fired = _fire(
                    PAYMENT_OVERDUE_ALERT, member, context, member.tenant,
                    payment_id=payment.pk, due_date=due_date,
                )
                if fired:
                    logger.info('nudge_fired', extra={
                        'event': PAYMENT_OVERDUE_ALERT,
                        'member_id': str(member.pk),
                        'payment_id': str(payment.pk),
                    })

    # ── 2. Risk-based trigger ─────────────────────────────────────────────────

    try:
        signal = MemberRevenueSignal.objects.get(member=member)
    except MemberRevenueSignal.DoesNotExist:
        return

    if signal.risk_level == RiskLevel.HIGH:
        context = {
            'member_id':   str(member.pk),
            'member_name': f'{member.first_name} {member.last_name}',
            'phone':       member.phone or '',
            'email':       member.email or '',
            'risk_reason': signal.risk_reason,
        }
        fired = _fire(
            RENEWAL_RISK_WARNING, member, context, member.tenant,
            payment_id=None, due_date=None,
        )
        if fired:
            logger.info('nudge_fired', extra={
                'event': RENEWAL_RISK_WARNING,
                'member_id': str(member.pk),
            })
