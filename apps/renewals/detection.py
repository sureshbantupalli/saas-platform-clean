"""
Renewal Detection Layer (Phase 1).

Scans active/recently-expired memberships and returns DetectionResult objects —
one per (membership, trigger_stage) pair that has not yet been logged.

READ-ONLY: never calls handle_event(), never writes to the database.
The Trigger Layer (Phase 2) acts on results and creates RenewalTriggerLog records.

Stage table
───────────────────────────────────────────────────────────────────────────────
days_left   trigger_type    eligible statuses
─────────   ────────────    ─────────────────
  7         expiring_7d     active only
  3         expiring_3d     active only
  1         expiring_1d     active only
 -1 to -7   expired         active (grace) or expired — recovery window
 < -7       (ignored)       too old; do not contact churned users

One membership emits at most one stage per detection run. Priority enforced as:
  expiring_1d > expiring_3d > expiring_7d > expired
(exact-day matching means only one expiring stage can fire per day; expired is
a separate gate checked after expiring stages are exhausted.)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from apps.memberships.models import Membership
from apps.renewals.models import RenewalTriggerLog, TriggerType

logger = logging.getLogger(__name__)

# Priority order: highest priority first so that a future `break` stops the
# search at the earliest (most urgent) matching stage.
TRIGGER_STAGES: list[tuple[str, int]] = [
    (TriggerType.EXPIRING_1D, 1),
    (TriggerType.EXPIRING_3D, 3),
    (TriggerType.EXPIRING_7D, 7),
]

# Memberships expired longer ago than this are silently ignored — avoids
# contacting long-churned users and limits the DB scan window.
RECOVERY_WINDOW_DAYS = 7

# ─── DB window explanation ────────────────────────────────────────────────────
# final_end_date is a Python property computed as:
#   end_date + sum(adjustment.days for all MembershipAdjustment rows)
#
# Because adjustments only ADD days (extensions, freezes, corrections are
# all positive in normal usage), final_end_date >= end_date always.
#
# We therefore DB-filter on end_date as a proxy:
#
#   Expiring stages (target = today + N, N ∈ {1, 3, 7}):
#     final_end_date = today + N  →  end_date ≤ today + N
#     DB upper bound: end_date ≤ today + 7 + 1 (window_end)  ✓
#     DB lower bound: end_date ≥ today + 1 - MAX_ADJ_DAYS    ✓
#
#   Expired stage (target = today - K, K ∈ {1..RECOVERY_WINDOW_DAYS}):
#     final_end_date = today - K  →  end_date ≤ final_end_date < today
#     DB lower bound: end_date ≥ today - RECOVERY_WINDOW_DAYS - MAX_ADJ_DAYS  ✓
#
# Any membership whose adjustments exceed MAX_ADJ_DAYS would escape the DB
# window. At 45 days this is beyond any realistic gym membership extension.
# Long-term fix: materialise final_end_date as a computed DB column.
# ─────────────────────────────────────────────────────────────────────────────
_MAX_ADJ_DAYS = 45  # adjustment buffer; see above

_MAX_STAGE_DAYS = max(days for _, days in TRIGGER_STAGES)  # 7


@dataclass(frozen=True)
class DetectionResult:
    """
    All fields Phase 2 needs to call handle_event() and write the trigger log.
    """
    membership_id: str
    member_id: str
    tenant_id: str
    trigger_type: str   # TriggerType value
    days_left: int      # positive → expiring; negative → expired
    expiry_date: date   # snapshot of final_end_date at detection time
    member_name: str
    phone: str
    email: str
    plan_name: str


class RenewalDetectionService:

    @staticmethod
    def detect_all(today: date | None = None) -> list[DetectionResult]:
        """
        Return all DetectionResults eligible for triggering as of `today`.

        `today` is injected for testability. In production it is always set
        from Django's timezone-aware clock (never datetime.date.today()) to
        avoid off-by-one errors when the server runs in a non-UTC timezone.

        Memberships already present in RenewalTriggerLog for the same
        (membership, trigger_type, expiry_date) triple are skipped — they
        have already been actioned in this renewal cycle.
        """
        if today is None:
            from django.utils import timezone
            today = timezone.now().date()

        # --- 1. DB-level filtering — NOT a full-table scan -------------------
        # See _MAX_ADJ_DAYS comment above for why end_date is a safe proxy.
        window_start = today - timedelta(days=RECOVERY_WINDOW_DAYS + _MAX_ADJ_DAYS)
        window_end   = today + timedelta(days=_MAX_STAGE_DAYS + 1)

        memberships = (
            Membership._base_manager
            .filter(
                status__in=['active', 'expired'],
                is_deleted=False,
                end_date__gte=window_start,
                end_date__lte=window_end,
            )
            .select_related('member', 'tenant', 'plan')
            .prefetch_related('adjustments')
        )

        membership_list = list(memberships)
        if not membership_list:
            return []

        # --- 2. Bulk-load existing trigger logs (idempotency) ----------------
        membership_ids = [m.id for m in membership_list]
        already_logged: set[tuple] = set(
            RenewalTriggerLog.base_objects
            .filter(membership_id__in=membership_ids)
            .values_list('membership_id', 'trigger_type', 'expiry_date')
        )

        # --- 3. Classify each membership — one stage per membership per run --
        results: list[DetectionResult] = []

        for membership in membership_list:
            expiry = membership.final_end_date
            if not expiry:
                continue

            days_left = (expiry - today).days
            member    = membership.member

            common = dict(
                membership_id=str(membership.id),
                member_id=str(member.id),
                tenant_id=str(membership.tenant_id),
                expiry_date=expiry,
                member_name=f'{member.first_name} {member.last_name}'.strip(),
                phone=member.phone or '',
                email=member.email or '',
                plan_name=membership.plan_name,
            )

            # ── Expiring stages (active memberships, future expiry only) ──
            # TRIGGER_STAGES is ordered 1d → 3d → 7d (highest priority first).
            # Exact-day matching means at most one branch is entered per day.
            # The break enforces the invariant explicitly.
            if membership.status == 'active' and days_left > 0:
                for trigger_type, target_days in TRIGGER_STAGES:
                    if days_left != target_days:
                        continue
                    if (membership.id, trigger_type, expiry) in already_logged:
                        logger.debug(
                            'Skipping already-logged trigger',
                            extra={
                                'membership_id': str(membership.id),
                                'trigger_type': trigger_type,
                            },
                        )
                        break  # logged → still consumed this stage slot
                    results.append(DetectionResult(
                        trigger_type=trigger_type,
                        days_left=days_left,
                        **common,
                    ))
                    break  # one expiring stage per membership per run

            # ── Expired-recovery stage ──
            # Separate if (not elif) so that grace-period memberships —
            # status='active' but final_end_date already past — are included.
            # Only fires within RECOVERY_WINDOW_DAYS of expiry; memberships
            # expired longer ago are silently ignored to prevent contacting
            # churned users.
            if days_left < 0 and days_left >= -RECOVERY_WINDOW_DAYS:
                if (membership.id, TriggerType.EXPIRED, expiry) not in already_logged:
                    results.append(DetectionResult(
                        trigger_type=TriggerType.EXPIRED,
                        days_left=days_left,
                        **common,
                    ))

        logger.info(
            'Renewal detection complete',
            extra={
                'today': str(today),
                'candidates_scanned': len(membership_list),
                'triggers_detected': len(results),
            },
        )
        return results
