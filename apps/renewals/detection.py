"""
Renewal Detection Layer (Phase 1).

Scans all active/recently-expired memberships and returns a list of
DetectionResult objects — one per (membership, trigger_stage) pair that
has not yet been logged in RenewalTriggerLog.

This layer is READ-ONLY. It never calls handle_event() and never writes
to the database. The Trigger Layer (Phase 2) is responsible for acting
on the results and creating RenewalTriggerLog records.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from apps.memberships.models import Membership
from apps.renewals.models import RenewalTriggerLog, TriggerType

logger = logging.getLogger(__name__)

TRIGGER_STAGES: list[tuple[str, int]] = [
    (TriggerType.EXPIRING_7D, 7),
    (TriggerType.EXPIRING_3D, 3),
    (TriggerType.EXPIRING_1D, 1),
]
RECOVERY_WINDOW_DAYS = 7

# Generous back-buffer to catch memberships extended via MembershipAdjustment.
# final_end_date >= end_date always, so end_date can be up to N days before
# the actual expiry. 45 days covers extreme multi-adjustment edge cases.
_ADJUSTMENT_BUFFER_DAYS = 45


@dataclass(frozen=True)
class DetectionResult:
    membership_id: str
    tenant_id: str
    trigger_type: str   # one of TriggerType values
    days_left: int      # negative for expired
    member_name: str
    phone: str
    email: str
    plan_name: str
    expiry_date: date
    member_id: str


class RenewalDetectionService:

    @staticmethod
    def detect_all(today: date | None = None) -> list[DetectionResult]:
        """
        Return all DetectionResults that are eligible for triggering.

        Memberships already present in RenewalTriggerLog for the same
        (trigger_type, expiry_date) triple are skipped — they have already
        been actioned in this renewal cycle.
        """
        if today is None:
            from django.utils import timezone
            today = timezone.now().date()

        # --- 1. Query candidate memberships ----------------------------------
        # We can't ORM-filter on final_end_date (it's a Python property), so
        # we use end_date as a conservative lower bound: final_end_date is
        # always >= end_date, so filtering end_date <= today + 7 covers all
        # memberships that could possibly be expiring within the next 7 days.
        # The back window covers expired-recovery candidates.
        window_start = today - timedelta(days=RECOVERY_WINDOW_DAYS + _ADJUSTMENT_BUFFER_DAYS)
        window_end = today + timedelta(days=max(d for _, d in TRIGGER_STAGES) + 1)

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

        # --- 3. Classify each membership -------------------------------------
        results: list[DetectionResult] = []

        for membership in membership_list:
            expiry = membership.final_end_date
            if not expiry:
                continue

            days_left = (expiry - today).days
            member = membership.member

            # Build common kwargs once per membership to avoid repetition
            common = dict(
                membership_id=str(membership.id),
                tenant_id=str(membership.tenant_id),
                member_name=f'{member.first_name} {member.last_name}'.strip(),
                phone=member.phone or '',
                email=member.email or '',
                plan_name=membership.plan_name,
                expiry_date=expiry,
                member_id=str(member.id),
            )

            # Expiring stages — only for active memberships
            if membership.status == 'active':
                for trigger_type, target_days in TRIGGER_STAGES:
                    if days_left != target_days:
                        continue
                    log_key = (membership.id, trigger_type, expiry)
                    if log_key in already_logged:
                        logger.debug(
                            'Skipping already-logged trigger',
                            extra={
                                'membership_id': str(membership.id),
                                'trigger_type': trigger_type,
                                'expiry_date': str(expiry),
                            },
                        )
                        continue
                    results.append(DetectionResult(
                        trigger_type=trigger_type,
                        days_left=days_left,
                        **common,
                    ))

            # Expired-recovery stage — active (grace) or expired memberships
            if days_left < 0 and days_left >= -RECOVERY_WINDOW_DAYS:
                log_key = (membership.id, TriggerType.EXPIRED, expiry)
                if log_key not in already_logged:
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
