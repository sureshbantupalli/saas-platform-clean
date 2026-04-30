"""
Phase 2: Renewal Trigger command.

Calls RenewalTriggerService.trigger_all() for a single tenant.
Fires handle_event() for each unlogged membership stage and writes
RenewalTriggerLog records for idempotency.

Usage:
    python manage.py trigger_renewals --tenant=<uuid>
    python manage.py trigger_renewals --tenant=<uuid> --date=2026-05-01
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.renewals.trigger import RenewalTriggerService


class Command(BaseCommand):
    help = 'Trigger renewal events for a tenant (Phase 2 — fires handle_event and writes logs)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            required=True,
            help='Tenant UUID',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Override today\'s date (YYYY-MM-DD) for testing',
        )

    def handle(self, *args, **options):
        from apps.core.models import Tenant

        try:
            tenant = Tenant.objects.get(id=options['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant {options['tenant']!r} not found.")

        today = None
        if options['date']:
            try:
                today = date.fromisoformat(options['date'])
            except ValueError:
                raise CommandError(f"Invalid date: {options['date']!r}. Use YYYY-MM-DD.")

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'\nRenewal Trigger — tenant: {tenant.name}'
                f'\n{"─" * 50}'
            )
        )

        result = RenewalTriggerService.trigger_all(tenant, today=today)

        self.stdout.write(
            self.style.SUCCESS(
                f'\n  Triggered : {result["triggered"]}'
                f'\n  Skipped   : {result["skipped"]}'
            )
        )
