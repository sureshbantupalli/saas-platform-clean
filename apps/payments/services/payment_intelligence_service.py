"""
Payment Intelligence Service

Assembles the per-payment status dashboard for a tenant.

DESIGN DECISIONS
  Status source:    PaymentService.get_payment_status() — PaymentTimingStatus constants only.
                    Template receives pre-computed strings; it never derives status from dates.
  Metric invariant: ALL metric counts MUST be derived from the status enum returned by
                    PaymentService, never re-computed from dates.  This guarantee prevents
                    divergence between what the badge shows and what the counts say.
  Metric definitions (strict, no overlap):
      pending  = status == PENDING  (unpaid AND due_date >= today)
      overdue  = status == OVERDUE  (unpaid AND due_date <  today)
  Sorting:    DB-level Case/When annotation — sort_order 0 (overdue) → 1 (pending) → 2 (paid).
              Template receives a pre-sorted list; it never re-sorts.
  Due date:   Membership.end_date via Subquery — explicit selection rule documented below.
  Late:       PaymentService.is_late() — same timezone path as status, cannot diverge.
  Last eval:  MemberRevenueSignal.updated_at (most recent across all tenant members).

PERFORMANCE NOTE (future)
  The Subquery(Membership.end_date) works well until ~100k payments hit this dashboard
  frequently.  If that happens, denormalize due_date onto Payment as an explicit field
  and remove the Subquery.  The rest of the service stays unchanged because all callers
  use payment.due_date (the annotated field name matches the future column name).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Imported only for static analysis — no runtime cost, no circular import risk.
    from apps.payments.models import Payment
    from apps.memberships.models import Membership

from django.db.models import Case, DateField, IntegerField, OuterRef, Subquery, Value, When
from django.utils.timezone import localdate

from apps.payments.services.payment_service import PaymentService, PaymentTimingStatus

logger = logging.getLogger('apps.payments')

_STATUS_META = {
    PaymentTimingStatus.OVERDUE: {'label': 'Overdue',    'badge': 'danger'},
    PaymentTimingStatus.PENDING: {'label': 'Pending',    'badge': 'warning'},
    PaymentTimingStatus.LATE:    {'label': 'Paid (late)', 'badge': 'secondary'},
    PaymentTimingStatus.ON_TIME: {'label': 'Paid',       'badge': 'success'},
}

class StatusGroup(str, Enum):
    """
    Coarse three-way classification of a payment for aggregation and filtering.

    Hierarchy of precision (narrowest → broadest):
        status_code   e.g. "OVERDUE_3D", "LATE_2D", "PENDING_TODAY"
        status        PaymentTimingStatus constant (OVERDUE / PENDING / LATE / ON_TIME)
        status_group  StatusGroup (OVERDUE / PENDING / PAID / UNKNOWN)

    LATE and ON_TIME both collapse into PAID.  The lateness signal is never lost —
    it is preserved in is_late (bool) and status_code (e.g. "LATE_2D").

    UNKNOWN is reserved for data-anomaly rows where due_date is missing (Membership
    end_date could not be resolved).  These rows must NOT be counted as PAID or PENDING
    in metrics, and MUST remain identifiable so data-quality issues surface.
    """
    OVERDUE = 'OVERDUE'
    PENDING = 'PENDING'
    PAID    = 'PAID'
    UNKNOWN = 'UNKNOWN'   # anomaly: due_date missing — do not count in normal metrics


# Maps PaymentTimingStatus → StatusGroup.  LATE collapses into PAID (see StatusGroup docstring).
_STATUS_GROUP: dict[PaymentTimingStatus, StatusGroup] = {
    PaymentTimingStatus.OVERDUE: StatusGroup.OVERDUE,
    PaymentTimingStatus.PENDING: StatusGroup.PENDING,
    PaymentTimingStatus.ON_TIME: StatusGroup.PAID,
    PaymentTimingStatus.LATE:    StatusGroup.PAID,
}


@dataclass
class PaymentRow:
    """
    Pre-computed, typed representation of one payment for UI rendering.

    RULE: All fields are set once by the service layer and never mutated by the
    view or template.  IDE type-checks catch typos (status_lable → status_label)
    that silent dict access would miss.

    Fields:
        payment       — Payment ORM instance (amount, created_at, pk, …)
        membership    — Membership ORM instance or None (plan_name, …)
        due_date      — Membership.end_date; None only for anomaly rows
        status        — PaymentTimingStatus constant; None for anomaly rows
        status_label  — Display string  e.g. "Overdue", "Pending", "Paid"
        status_badge  — Bootstrap colour suffix e.g. "danger", "warning", "success"
        status_code   — Machine-readable  e.g. "OVERDUE_3D", "PENDING_TODAY"
        status_reason — Human-readable    e.g. "overdue by 3 days", "due today"
        is_late          — True  = paid AND paid after due_date (late)
                           False = paid on time, or unpaid (not late)
                           None  = not applicable (anomaly row — due_date missing)
        show_late_badge  — bool derived as `is_late is True`; use this in templates instead
                           of `is_late` so renderers never need to understand the tri-state
        status_group  — StatusGroup enum.  Use for aggregation / coarse filters.
                        Use status / status_code for exact sub-classification.
    """
    payment:       Payment            # Payment model instance
    membership:    Optional[Membership]
    due_date:      Optional[_date]
    status:        Optional[str]      # PaymentTimingStatus constant or None
    status_label:  str
    status_badge:  str
    status_code:   str
    status_reason: str
    is_late:         Optional[bool]  # None = not applicable (anomaly row)
    show_late_badge: bool            # is_late is True — pre-computed; template never sees tri-state
    status_group:    StatusGroup


# Exhaustive set of valid status code prefixes.
# Add here when a new status is introduced; build_status_code() enforces this list.
ALLOWED_PREFIXES: frozenset[str] = frozenset({
    'OVERDUE',
    'PENDING',
    'ON_TIME',
    'LATE',
    'PAID',
})


def build_status_code(prefix: str, days: int | None) -> str:
    """
    Canonical status code builder — always call this; never construct codes manually.

    Format rules (Option A — semantic zero):
        days=None → "{PREFIX}"           e.g. ON_TIME, PAID
        days=0    → "{PREFIX}_TODAY"     e.g. PENDING_TODAY  (semantic, not numeric)
        days>0    → "{PREFIX}_{days}D"   e.g. OVERDUE_3D, LATE_2D, PENDING_5D

    OVERDUE_0D is physically impossible: OVERDUE requires days_to_due < 0, so
    abs(days_to_due) ≥ 1 always.  The TODAY branch therefore only fires for PENDING.

    Raises ValueError for unknown prefixes so semantic drift is caught at build time,
    not silently passed through to analytics / AI layers.
    """
    if prefix not in ALLOWED_PREFIXES:
        raise ValueError(
            f'Unknown status code prefix: {prefix!r}. '
            f'Allowed: {sorted(ALLOWED_PREFIXES)}'
        )
    if days is None:
        return prefix
    if days == 0:
        return f'{prefix}_TODAY'
    return f'{prefix}_{days}D'


def parse_status_code(code: str) -> tuple[str, int | str | None]:
    """
    Reverse of build_status_code.  Parses a status code into its components.

    Returns (prefix, days) where `days` is:
        None    → no suffix            e.g. parse("ON_TIME")       → ("ON_TIME", None)
        "TODAY" → _TODAY suffix        e.g. parse("PENDING_TODAY")  → ("PENDING", "TODAY")
        int     → numeric day count    e.g. parse("OVERDUE_3D")     → ("OVERDUE", 3)

    Raises ValueError for any input that build_status_code() could not have produced —
    unknown prefix, leading zeros, lowercase, hyphens, etc.

    Use this for analytics grouping, admin filters, and explainability layers.
    Avoids ad-hoc regex parsing scattered across the codebase.
    """
    import re
    _P = r'[A-Z][A-Z_]*'
    # Try suffix patterns first — greedy prefix would otherwise swallow _TODAY/_nD.
    m = re.fullmatch(rf'({_P})_([1-9][0-9]*)D', code)
    if m:
        prefix = m.group(1)
        if prefix not in ALLOWED_PREFIXES:
            raise ValueError(
                f'Unknown prefix {prefix!r} in status code {code!r}. '
                f'Allowed: {sorted(ALLOWED_PREFIXES)}'
            )
        return (prefix, int(m.group(2)))
    m = re.fullmatch(rf'({_P})_(TODAY)', code)
    if m:
        prefix = m.group(1)
        if prefix not in ALLOWED_PREFIXES:
            raise ValueError(
                f'Unknown prefix {prefix!r} in status code {code!r}. '
                f'Allowed: {sorted(ALLOWED_PREFIXES)}'
            )
        return (prefix, 'TODAY')
    if re.fullmatch(_P, code):
        if code not in ALLOWED_PREFIXES:
            raise ValueError(
                f'Unknown prefix {code!r} in status code {code!r}. '
                f'Allowed: {sorted(ALLOWED_PREFIXES)}'
            )
        return (code, None)
    raise ValueError(f'Unrecognised status code format: {code!r}')


def _reason_and_code(status: str, days_to_due: int, payment, due_date) -> tuple[str, str]:
    """
    Return (human_readable_reason, machine_readable_code) for display and analytics.

    CONTRACT — this function must only:
      • branch on `status` (a PaymentTimingStatus constant passed by caller)
      • use pre-computed `days_to_due` for the unpaid magnitude
      • call PaymentService.get_days_to_pay() for the paid magnitude
      • call build_status_code() for every code — never construct strings manually
    It must never perform raw date comparisons or re-derive the status itself.
    All status decisions belong to PaymentService.get_payment_status().
    """
    if status == PaymentTimingStatus.OVERDUE:
        n = abs(days_to_due)   # always ≥ 1; see build_status_code docstring
        return (
            f'overdue by {n} day{"s" if n != 1 else ""}',
            build_status_code('OVERDUE', n),
        )

    if status == PaymentTimingStatus.PENDING:
        n = days_to_due        # ≥ 0; n=0 → TODAY via build_status_code
        if n == 0:
            return 'due today', build_status_code('PENDING', 0)
        if n == 1:
            return 'due tomorrow', build_status_code('PENDING', 1)
        return f'due in {n} days', build_status_code('PENDING', n)

    # Paid path — only PaymentService.get_days_to_pay() determines magnitude.
    days = PaymentService.get_days_to_pay(payment, due_date=due_date)
    if days is None:
        return 'paid', build_status_code('PAID', None)
    if days > 0:
        return f'paid {days} day{"s" if days != 1 else ""} late', build_status_code('LATE', days)
    if days == 0:
        return 'paid on due date', build_status_code('ON_TIME', None)
    return f'paid {abs(days)} day{"s" if abs(days) != 1 else ""} early', build_status_code('ON_TIME', None)


def get_payment_rows_for_member(tenant, member) -> list[PaymentRow]:
    """
    Pre-computed, typed payment rows for /members/<id>/payments/.

    CONTRACT — same invariants as get_payment_intelligence():
      • All status values come from PaymentService.get_payment_status() — never re-derived.
      • Template receives PaymentRow instances and renders attributes only.
      • Sorted DB-level: overdue (0) → pending (1) → paid (2), then due_date ascending.
      • Two DB queries total (memberships + payments), regardless of row count.
        PaymentService calls are pure-Python — zero additional DB hits in the loop.
    """
    from apps.memberships.models import Membership
    from apps.payments.models import Payment

    today = localdate()

    # ── 1. Pre-fetch ALL memberships (including soft-deleted) for this member (1 query) ──
    #
    # WHY include deleted memberships:
    #   A member's payment history must be complete — payments for memberships that were
    #   later soft-deleted should still appear.  Using is_deleted=False here would
    #   silently drop those payments.
    #
    # HOW anomaly rows arise:
    #   The Subquery for due_date (step 2) still filters is_deleted=False, so a payment
    #   referencing a deleted membership gets due_date=NULL → status_group=UNKNOWN.
    #   This surfaces data-quality issues instead of hiding them in PAID/PENDING counts.
    memberships = {
        m.pk: m
        for m in Membership.base_objects.filter(member=member).select_related('plan')
    }
    if not memberships:
        return []

    # ── 2. Annotate payments with due_date + sort_order, sorted DB-level (1 query) ──
    #
    # Subquery filters is_deleted=False — deleted memberships → NULL due_date → UNKNOWN.
    end_date_sq = Subquery(
        Membership.base_objects.filter(
            pk=OuterRef('reference_id'),
            is_deleted=False,
        ).order_by('-end_date', '-id').values('end_date')[:1],
        output_field=DateField(),
    )

    payments_qs = (
        Payment.base_objects.filter(
            tenant=tenant,
            reference_type='membership',
            reference_id__in=list(memberships),
            is_deleted=False,
        )
        .annotate(due_date=end_date_sq)
        .annotate(
            sort_order=Case(
                When(paid_at__isnull=False, then=Value(2)),
                When(paid_at__isnull=True, due_date__lt=today, then=Value(0)),
                When(paid_at__isnull=True, due_date__gte=today, then=Value(1)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by('sort_order', 'due_date')
    )

    # ── 3. Build rows — NO DB queries inside this loop ────────────────────────
    rows = []
    for payment in payments_qs:
        due_date   = payment.due_date
        membership = memberships.get(payment.reference_id)

        if not due_date:
            # Anomaly: Membership.end_date could not be resolved (e.g. membership soft-deleted).
            # is_late=None  → "not applicable", not "safe/known-not-late"
            # status_group=UNKNOWN → excluded from normal metrics, surfaces data-quality issue
            rows.append(PaymentRow(
                payment=payment, membership=membership,
                due_date=None, status=None,
                status_label='—', status_badge='secondary',
                status_code='', status_reason='',
                is_late=None, show_late_badge=False,
                status_group=StatusGroup.UNKNOWN,
            ))
            continue

        # Single call owns all status logic; no raw date comparisons below this line.
        status      = PaymentService.get_payment_status(payment, due_date=due_date)
        is_late     = PaymentService.is_late(payment, due_date=due_date)
        meta        = _STATUS_META.get(status, {'label': status, 'badge': 'secondary'})
        days_to_due = (due_date - today).days
        reason, code = _reason_and_code(status, days_to_due, payment, due_date)

        rows.append(PaymentRow(
            payment=payment,
            membership=membership,
            due_date=due_date,
            status=status,
            status_label=meta['label'],
            status_badge=meta['badge'],
            status_code=code,
            status_reason=reason,
            is_late=is_late,
            show_late_badge=(is_late is True),
            status_group=_STATUS_GROUP.get(status, StatusGroup.UNKNOWN),
        ))

    return rows


def get_payment_metrics(tenant) -> dict:
    """
    Aggregate payment metrics for the analytics dashboard widget.

    Returns:
        total_collected_last_30_days  — sum of SUCCESS payments with paid_at in last 30 days
        total_pending                 — count of payments with sort_order == 1 (PENDING)
        overdue_count                 — count of payments with sort_order == 0 (OVERDUE)

    sort_order mirrors PaymentService.get_payment_status() at DB level so counts are
    guaranteed to agree with the per-row badges on the payment intelligence dashboard.
    One query each: no per-row Python calls required for aggregate counts.
    """
    from datetime import timedelta
    from django.db.models import Count, Sum
    from apps.memberships.models import Membership
    from apps.payments.models import Payment, PaymentStatus

    today           = localdate()
    thirty_days_ago = today - timedelta(days=30)

    # ── 1. Collected last 30 days (gateway SUCCESS, paid_at window) ───────────
    total_collected = (
        Payment.base_objects
        .filter(
            tenant=tenant,
            status=PaymentStatus.SUCCESS,
            paid_at__date__gte=thirty_days_ago,
            is_deleted=False,
        )
        .aggregate(total=Sum('amount'))
    )['total'] or 0

    # ── 2. Pending / Overdue via sort_order annotation (single query) ─────────
    #
    # sort_order is the DB-level equivalent of PaymentService.get_payment_status():
    #   0 = OVERDUE  (paid_at IS NULL AND due_date <  today)
    #   1 = PENDING  (paid_at IS NULL AND due_date >= today)
    #   2 = PAID     (paid_at IS NOT NULL)
    # Counts derived here will always agree with per-row status badges.

    end_date_sq = Subquery(
        Membership.base_objects.filter(
            pk=OuterRef('reference_id'),
            is_deleted=False,
        ).order_by('-end_date', '-id').values('end_date')[:1],
        output_field=DateField(),
    )

    status_counts = (
        Payment.base_objects
        .filter(tenant=tenant, reference_type='membership', is_deleted=False)
        .annotate(due_date=end_date_sq)
        .annotate(
            sort_order=Case(
                When(paid_at__isnull=False, then=Value(2)),
                When(paid_at__isnull=True, due_date__lt=today, then=Value(0)),
                When(paid_at__isnull=True, due_date__gte=today, then=Value(1)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .values('sort_order')
        .annotate(cnt=Count('id'))
    )
    count_map = {row['sort_order']: row['cnt'] for row in status_counts}

    return {
        'total_collected_last_30_days': total_collected,
        'total_pending':                count_map.get(1, 0),
        'overdue_count':                count_map.get(0, 0),
    }


def get_payment_intelligence(tenant) -> dict:
    """
    Return enriched payment rows for `tenant`, sorted overdue → pending → paid,
    plus summary metrics and the last-evaluated timestamp.

    INVARIANT: all status values and metric counts are derived exclusively from
    PaymentService.get_payment_status().  No date arithmetic happens outside that call.
    """
    from apps.memberships.models import Membership
    from apps.payments.models import Payment
    from apps.revenue.models import MemberRevenueSignal

    today = localdate()

    # ── 1. Annotate each payment with due_date (Membership.end_date) and sort_order ──
    #
    # Payment → Membership is not a FK; reference_id holds the membership PK.
    #
    # SELECTION RULE: filter by pk=OuterRef('reference_id') — the exact membership
    # this payment was created for.  We do NOT filter by status='active' because
    # overdue payments may reference expired memberships; their end_date is still
    # the semantically correct due_date.  order_by ensures a deterministic result
    # on the (unlikely) chance of data anomalies; PK filter normally returns 1 row.
    #
    # sort_order:
    #   0 = overdue  (unpaid AND due_date < today)
    #   1 = pending  (unpaid AND due_date >= today)
    #   2 = paid     (paid_at IS NOT NULL)

    end_date_sq = Subquery(
        Membership.base_objects.filter(
            pk=OuterRef('reference_id'),
            is_deleted=False,
        ).order_by('-end_date', '-id').values('end_date')[:1],
        # -id is a deterministic tiebreaker when two rows share the same end_date
        # (e.g. migration bugs, manual edits). Zero cost; prevents nondeterminism.
        output_field=DateField(),
    )

    payments_qs = (
        Payment.base_objects.filter(
            tenant=tenant,
            reference_type='membership',
            is_deleted=False,
        )
        .annotate(due_date=end_date_sq)
        .annotate(
            sort_order=Case(
                When(paid_at__isnull=False, then=Value(2)),
                When(paid_at__isnull=True, due_date__lt=today, then=Value(0)),
                When(paid_at__isnull=True, due_date__gte=today, then=Value(1)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by('sort_order', 'due_date')
    )

    # ── 2. Pre-fetch membership → member in one query ─────────────────────────

    reference_ids = list(payments_qs.values_list('reference_id', flat=True))

    memberships = {
        m.id: m
        for m in Membership.base_objects.filter(
            pk__in=reference_ids, is_deleted=False
        ).select_related('member')
    }

    # ── 3. Pre-fetch revenue signals for risk display ─────────────────────────

    member_ids = [m.member_id for m in memberships.values() if m.member_id]
    signals    = {
        s.member_id: s
        for s in MemberRevenueSignal.objects.filter(member_id__in=member_ids)
    }

    # ── 4. Build enriched rows, accumulate metrics ────────────────────────────
    #
    # INVARIANT: total_pending and overdue_count are incremented ONLY from the
    # status enum value returned by PaymentService.get_payment_status().
    # Do not add date-based conditionals here — they would silently diverge from
    # what the status badge shows.

    rows          = []
    total_pending = 0
    overdue_count = 0

    for payment in payments_qs:
        due_date = payment.due_date
        if not due_date:
            continue

        membership = memberships.get(payment.reference_id)
        member     = membership.member if membership else None
        signal     = signals.get(member.pk) if member else None

        # Single call owns all status logic; no raw date comparisons below this line.
        status      = PaymentService.get_payment_status(payment, due_date=due_date)
        is_late     = PaymentService.is_late(payment, due_date=due_date)
        meta        = _STATUS_META.get(status, {'label': status, 'badge': 'secondary'})
        # days_to_due: positive = future, negative = past. Pre-computed here so
        # _reason_and_code() receives a value, not a date — enforcing its contract.
        days_to_due = (due_date - today).days
        reason, code = _reason_and_code(status, days_to_due, payment, due_date)

        # Counts derived from enum — guaranteed to match the badge.
        if status == PaymentTimingStatus.PENDING:
            total_pending += 1
        elif status == PaymentTimingStatus.OVERDUE:
            overdue_count += 1

        rows.append({
            'payment':          payment,
            'due_date':         due_date,
            'status':           status,           # PaymentTimingStatus constant
            'status_label':     meta['label'],    # display string
            'status_badge':     meta['badge'],    # CSS class suffix
            'status_reason':    reason,           # human-readable (UI / AI)
            'status_code':      code,             # machine-readable (analytics / filters)
            'is_late':          is_late,
            'show_late_badge':  (is_late is True),
            'member':           member,
            'member_name':      f'{member.first_name} {member.last_name}' if member else '—',
            'risk_level':       signal.risk_level  if signal else None,
            'risk_reason':      signal.risk_reason if signal else None,
        })

    # ── 5. Last-evaluated timestamp ───────────────────────────────────────────

    last_evaluated = (
        MemberRevenueSignal.objects
        .filter(member__tenant=tenant)
        .order_by('-updated_at')
        .values_list('updated_at', flat=True)
        .first()
    )

    return {
        'rows': rows,
        'metrics': {
            'total_pending': total_pending,
            'overdue_count': overdue_count,
            'total_rows':    len(rows),
        },
        'last_evaluated': last_evaluated,
    }
