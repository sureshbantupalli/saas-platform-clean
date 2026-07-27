"""
Retry Engine command — cron entry point.

Processes all failed MessageAttempt records that are eligible for retry
according to configured RetryRules.

Cron example (every 15 minutes):
    */15 * * * * /path/to/venv/bin/python manage.py run_retries

Usage:
    python manage.py run_retries
"""
from django.core.management.base import BaseCommand

from apps.engagement.retry_service import process_retries


class Command(BaseCommand):
    help = 'Retry failed messages according to configured RetryRules'

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'\nRetry Engine'
                f'\n{"─" * 50}'
            )
        )

        summary = process_retries()

        self.stdout.write(
            self.style.SUCCESS(
                f'\n  Processed : {summary["processed"]}'
                f'\n  Sent      : {summary["sent"]}'
                f'\n  Failed    : {summary["failed"]}'
                f'\n  Skipped   : {summary["skipped"]}'
            )
        )
