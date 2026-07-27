"""
Management command: run_nudges

Sweeps every tenant and calls evaluate_member() for each active member,
firing payment_due_reminder, payment_overdue_alert, and renewal_risk_warning
events through the existing communication pipeline.

All events are idempotent (NudgeLog unique constraint) — safe to run on cron.

Usage:
    python manage.py run_nudges
    python manage.py run_nudges --tenant-id <uuid>
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Evaluate and fire revenue nudge events for all members.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-id',
            dest='tenant_id',
            default=None,
            help='Limit to a single tenant UUID (default: all tenants).',
        )

    def handle(self, *args, **options):
        from apps.core.models import Tenant
        from members.models import Member
        from apps.revenue.services.nudge_trigger_service import evaluate_member

        from apps.core.platform import exclude_platform

        tenant_id = options.get('tenant_id')
        if tenant_id:
            tenants = Tenant.objects.filter(pk=tenant_id)
        else:
            # The internal ANJASI tenant has no members to nudge.
            tenants = exclude_platform(Tenant.objects.all())

        total_members = 0
        total_errors  = 0

        for tenant in tenants:
            members = Member.base_objects.filter(
                tenant=tenant,
                is_deleted=False,
            )
            tenant_count = 0
            for member in members:
                try:
                    evaluate_member(member)
                    tenant_count += 1
                except Exception as exc:
                    total_errors += 1
                    self.stderr.write(
                        f'  ERROR member={member.pk} tenant={tenant.pk}: {exc}'
                    )

            total_members += tenant_count
            self.stdout.write(f'  {tenant.name}: evaluated {tenant_count} members')

        self.stdout.write(self.style.SUCCESS(
            f'run_nudges complete — members_evaluated={total_members} errors={total_errors}'
        ))
