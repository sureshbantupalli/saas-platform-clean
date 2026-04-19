"""
management command: retry_failed_messages

Retries FAILED CommunicationLog entries that have not yet reached max_retries.
Designed to run as a scheduled job (cron, Celery beat, etc.):

    python manage.py retry_failed_messages               # all tenants
    python manage.py retry_failed_messages --tenant <subdomain>
    python manage.py retry_failed_messages --max-retries 5

Exponential backoff is advisory — the scheduler controls call frequency.
A simple approach: run every 5 minutes; retry_count cap limits total attempts.
"""
import logging

from django.core.management.base import BaseCommand

from apps.communications.services.retry_service import retry_failed_messages, MAX_RETRIES

logger = logging.getLogger("apps.communications")


class Command(BaseCommand):
    help = "Retry FAILED communication messages up to max_retries times."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Subdomain of a specific tenant to retry for (default: all tenants).",
        )
        parser.add_argument(
            "--max-retries",
            type=int,
            default=MAX_RETRIES,
            help=f"Maximum number of retry attempts (default: {MAX_RETRIES}).",
        )

    def handle(self, *args, **options):
        tenant_subdomain = options.get("tenant")
        max_retries      = options["max_retries"]
        tenant           = None

        if tenant_subdomain:
            from apps.core.models import Tenant
            try:
                tenant = Tenant.objects.get(subdomain=tenant_subdomain)
            except Tenant.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Tenant '{tenant_subdomain}' not found."))
                return

        succeeded = retry_failed_messages(tenant=tenant, max_retries=max_retries)
        self.stdout.write(
            self.style.SUCCESS(f"Retry complete: {succeeded} message(s) sent successfully.")
        )
