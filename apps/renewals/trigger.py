"""
Renewal Trigger Layer (Phase 2).

Takes DetectionResults and fires exactly one handle_event() call per
(membership, trigger_type, expiry_date) triple, then writes a
RenewalTriggerLog to prevent re-firing.

Rules:
  - Never calls send_message() directly.
  - Never touches membership data, payments, or CTA logic.
  - Only: check → trigger → log.
"""
import logging

from django.db import IntegrityError

from apps.communications.services.communication_service import handle_event
from apps.renewals.detection import RenewalDetectionService
from apps.renewals.models import RenewalTriggerLog

logger = logging.getLogger(__name__)


class RenewalTriggerService:

    @staticmethod
    def trigger_all(tenant, today=None) -> dict[str, int]:
        """
        Detect and trigger renewal events for `tenant` as of `today`.

        Returns {"triggered": N, "skipped": N}.

        triggered — handle_event called and log written.
        skipped   — idempotency check fired (race condition) or IntegrityError.
        """
        results = RenewalDetectionService.detect_all(today=today, tenant=tenant)

        triggered = 0
        skipped   = 0

        for item in results:
            # Belt-and-suspenders idempotency check. detect_all already filters
            # logged items, but this catches the race window between detection
            # and this trigger attempt (e.g. two workers running simultaneously).
            if RenewalTriggerLog.base_objects.filter(
                membership_id=item.membership_id,
                trigger_type=item.trigger_type,
                expiry_date=item.expiry_date,
            ).exists():
                skipped += 1
                logger.debug(
                    'renewal_trigger_skipped_race',
                    extra={
                        'membership_id': item.membership_id,
                        'trigger_type':  item.trigger_type,
                    },
                )
                continue

            context = {
                'member_id':    item.member_id,
                'member_name':  item.member_name,
                'phone':        item.phone,
                'email':        item.email,
                'membership_id': item.membership_id,
                'plan_name':    item.plan_name,
                'expiry_date':  str(item.expiry_date),
                'days_left':    str(item.days_left),
            }

            handle_event(item.trigger_type, context, tenant)

            try:
                RenewalTriggerLog.base_objects.create(
                    tenant=tenant,
                    membership_id=item.membership_id,
                    trigger_type=item.trigger_type,
                    expiry_date=item.expiry_date,
                )
                triggered += 1
                logger.info(
                    'renewal_triggered',
                    extra={
                        'membership_id': item.membership_id,
                        'trigger_type':  item.trigger_type,
                        'tenant_id':     str(tenant.id),
                    },
                )
            except IntegrityError:
                # Two workers triggered simultaneously; log write lost the race.
                # handle_event already fired — count as skipped, not an error.
                skipped += 1
                logger.warning(
                    'renewal_trigger_integrity_race',
                    extra={
                        'membership_id': item.membership_id,
                        'trigger_type':  item.trigger_type,
                    },
                )

        logger.info(
            'renewal_trigger_complete',
            extra={
                'tenant_id': str(tenant.id),
                'triggered': triggered,
                'skipped':   skipped,
            },
        )
        return {'triggered': triggered, 'skipped': skipped}
