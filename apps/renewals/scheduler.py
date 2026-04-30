"""
Renewal Scheduler (Phase 3).

run_daily_renewals(today=None)
    Iterates all active tenants, calls RenewalTriggerService.trigger_all()
    for each, logs outcomes, and never stops on a single-tenant failure.

run_renewals_task()
    Celery-ready wrapper. When Celery is wired in, replace this with:

        @shared_task
        def run_renewals_task():
            return run_daily_renewals()

    No Celery dependency imported here.

Cron example (runs daily at 09:00):
    0 9 * * * /path/to/venv/bin/python manage.py run_renewals
"""
import logging

from django.utils import timezone

from apps.renewals.trigger import RenewalTriggerService

logger = logging.getLogger(__name__)


def run_daily_renewals(today=None) -> dict:
    """
    Run renewal triggers for every active tenant.

    Returns:
        {
            "tenants_processed": int,   # tenants where trigger_all succeeded
            "total_triggered":   int,
            "total_skipped":     int,
            "failed_tenants":    list[str],  # tenant IDs that raised an exception
        }
    """
    if today is None:
        today = timezone.now().date()

    from apps.core.models import Tenant
    tenants = Tenant.objects.filter(is_active=True)

    tenants_processed = 0
    total_triggered   = 0
    total_skipped     = 0
    failed_tenants: list[str] = []

    for tenant in tenants:
        try:
            result = RenewalTriggerService.trigger_all(tenant, today=today)
            total_triggered   += result['triggered']
            total_skipped     += result['skipped']
            tenants_processed += 1
            logger.info(
                'renewals_triggered',
                extra={
                    'tenant_id': str(tenant.id),
                    'triggered': result['triggered'],
                    'skipped':   result['skipped'],
                    'date':      str(today),
                },
            )
        except Exception as exc:
            failed_tenants.append(str(tenant.id))
            logger.error(
                'renewals_failed',
                extra={
                    'tenant_id': str(tenant.id),
                    'error':     str(exc),
                    'date':      str(today),
                },
            )
            # Failure is isolated to this tenant — continue with the rest.

    return {
        'tenants_processed': tenants_processed,
        'total_triggered':   total_triggered,
        'total_skipped':     total_skipped,
        'failed_tenants':    failed_tenants,
    }


def run_renewals_task() -> dict:
    """
    Celery-ready wrapper around run_daily_renewals().

    To activate as a Celery task, add the decorator in a tasks.py file:

        from celery import shared_task
        from apps.renewals.scheduler import run_daily_renewals

        @shared_task(name='renewals.run_daily')
        def run_renewals_task():
            return run_daily_renewals()

    This function stays free of any Celery import.
    """
    return run_daily_renewals()
