"""
Renewal Scheduler command — cron entry point (Phase 3).

Runs renewal triggers for all active tenants, or a single tenant.
This replaces the Phase 1 detection-only command.

Cron example (daily at 09:00):
    0 9 * * * /path/to/venv/bin/python manage.py run_renewals

Usage:
    python manage.py run_renewals
    python manage.py run_renewals --date 2026-05-01
    python manage.py run_renewals --tenant <uuid>
"""
from datetime import date as date_type

from django.core.management.base import BaseCommand, CommandError

from apps.renewals.scheduler import run_daily_renewals
from apps.renewals.trigger import RenewalTriggerService


class Command(BaseCommand):
    help = 'Run renewal triggers for all active tenants (cron entry point)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Override today\'s date (YYYY-MM-DD)',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            help='Run only this tenant UUID (skips all others)',
        )

    def handle(self, *args, **options):
        today = None
        if options['date']:
            try:
                today = date_type.fromisoformat(options['date'])
            except ValueError:
                raise CommandError(
                    f"Invalid date: {options['date']!r}. Use YYYY-MM-DD."
                )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'\nRenewal Scheduler'
                f'\n{"─" * 50}'
            )
        )

        if options.get('tenant'):
            self._run_single_tenant(options['tenant'], today)
        else:
            self._run_all_tenants(today)

    def _run_single_tenant(self, tenant_id: str, today) -> None:
        from apps.core.models import Tenant
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant {tenant_id!r} not found.")

        result = RenewalTriggerService.trigger_all(tenant, today=today)

        self.stdout.write(
            self.style.SUCCESS(
                f'\n  Tenant    : {tenant.name}'
                f'\n  Triggered : {result["triggered"]}'
                f'\n  Skipped   : {result["skipped"]}'
            )
        )

    def _run_all_tenants(self, today) -> None:
        summary = run_daily_renewals(today=today)

        self.stdout.write(
            self.style.SUCCESS(
                f'\n  Tenants processed : {summary["tenants_processed"]}'
                f'\n  Total triggered   : {summary["total_triggered"]}'
                f'\n  Total skipped     : {summary["total_skipped"]}'
            )
        )

        if summary['failed_tenants']:
            self.stdout.write(
                self.style.ERROR(
                    f'\n  Failed tenants ({len(summary["failed_tenants"])}) : '
                    + ', '.join(summary['failed_tenants'])
                )
            )
