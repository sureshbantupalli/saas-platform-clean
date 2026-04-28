"""
Phase 1: Renewal Detection command.

Scans memberships and prints what WOULD be triggered. Does NOT call
handle_event() and does NOT write to RenewalTriggerLog. Safe to run
at any time without side effects.

Usage:
    python manage.py run_renewals
    python manage.py run_renewals --date 2026-05-01   # simulate a specific date
    python manage.py run_renewals --tenant <id>       # limit to one tenant
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.renewals.detection import RenewalDetectionService
from apps.renewals.models import TriggerType

_STAGE_LABEL = {
    TriggerType.EXPIRING_7D: 'EXPIRING in 7 days',
    TriggerType.EXPIRING_3D: 'EXPIRING in 3 days',
    TriggerType.EXPIRING_1D: 'EXPIRING tomorrow',
    TriggerType.EXPIRED:     'EXPIRED (recovery)',
}


class Command(BaseCommand):
    help = 'Detect memberships due for renewal actions (Phase 1 — detection only, no triggers fired)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Override today\'s date (YYYY-MM-DD) for testing',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            help='Limit output to a specific tenant ID',
        )

    def handle(self, *args, **options):
        today = None
        if options['date']:
            try:
                today = date.fromisoformat(options['date'])
            except ValueError:
                raise CommandError(f"Invalid date format: {options['date']}. Use YYYY-MM-DD.")

        tenant_filter = options.get('tenant')

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'\nRenewal Detection (Phase 1 — read-only)'
                f'\n{"─" * 50}'
            )
        )

        results = RenewalDetectionService.detect_all(today=today)

        if tenant_filter:
            results = [r for r in results if str(r.tenant_id) == tenant_filter]

        if not results:
            self.stdout.write(self.style.SUCCESS('\nNo renewal triggers detected.'))
            return

        # Group by trigger type for readable output
        by_stage: dict[str, list] = {}
        for r in results:
            by_stage.setdefault(r.trigger_type, []).append(r)

        total = 0
        for stage_key in [TriggerType.EXPIRING_7D, TriggerType.EXPIRING_3D,
                          TriggerType.EXPIRING_1D, TriggerType.EXPIRED]:
            stage_results = by_stage.get(stage_key, [])
            if not stage_results:
                continue

            label = _STAGE_LABEL[stage_key]
            self.stdout.write(self.style.WARNING(f'\n{label} ({len(stage_results)})'))
            self.stdout.write('─' * 50)

            for r in stage_results:
                self.stdout.write(
                    f'  {r.member_name:<25} {r.plan_name:<20} '
                    f'expires {r.expiry_date}  '
                    f'tenant={r.tenant_id[:8]}  '
                    f'id={r.membership_id[:8]}'
                )
                total += 1

        self.stdout.write(
            self.style.SUCCESS(f'\n{total} trigger(s) detected. '
                               f'(Phase 1 — no events fired, no logs written)')
        )
