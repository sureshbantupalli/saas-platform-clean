from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate

from apps.lifecycles.models import LifecycleRun
from apps.core.tenant_context import get_current_tenant


class LifecycleHealthService:

    # -----------------------------------------------------
    # Tenant Context Handler (FIXED)
    # -----------------------------------------------------
    @staticmethod
    def _get_tenant():
        return get_current_tenant()  # can be None (platform admin)

    # -----------------------------------------------------
    # Dashboard Summary
    # -----------------------------------------------------
    @staticmethod
    def get_dashboard_summary():
        tenant = LifecycleHealthService._get_tenant()

        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)
        one_day_ago = now - timedelta(days=1)

        queryset = LifecycleRun.objects

        # ✅ Apply filter only if tenant exists
        if tenant:
            queryset = queryset.filter(tenant=tenant)

        runs_7d = queryset.filter(started_at__gte=seven_days_ago)
        runs_24h = queryset.filter(started_at__gte=one_day_ago)

        last_run = queryset.order_by('-started_at').first()

        return {
            "last_status": last_run.status if last_run else "N/A",
            "last_duration": last_run.duration_ms if last_run else 0,
            "runs_24h": runs_24h.count(),
            "failures_7d": runs_7d.filter(
                status=LifecycleRun.Status.FAILED
            ).count(),
            "avg_duration_7d": runs_7d.aggregate(
                avg=Avg("duration_ms")
            )["avg"] or 0
        }

    # -----------------------------------------------------
    # Trend Data
    # -----------------------------------------------------
    @staticmethod
    def get_trend_data():
        tenant = LifecycleHealthService._get_tenant()

        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)

        queryset = LifecycleRun.objects

        if tenant:
            queryset = queryset.filter(tenant=tenant)

        runs = (
            queryset
            .filter(started_at__gte=seven_days_ago)
            .annotate(day=TruncDate("started_at"))
            .values('day')
            .annotate(
                total_runs=Count('id'),
                failures=Count(
                    'id',
                    filter=Q(status=LifecycleRun.Status.FAILED)
                ),
                avg_duration=Avg('duration_ms')
            )
            .order_by('day')
        )

        labels = []
        total_runs = []
        failures = []

        for r in runs:
            labels.append(str(r['day']))
            total_runs.append(r['total_runs'])
            failures.append(r['failures'])

        return {
            "labels": labels,
            "total_runs": total_runs,
            "failures": failures,
        }

    # -----------------------------------------------------
    # Recent Runs
    # -----------------------------------------------------
    @staticmethod
    def get_recent_runs(limit=20):
        tenant = LifecycleHealthService._get_tenant()

        queryset = LifecycleRun.objects

        if tenant:
            queryset = queryset.filter(tenant=tenant)

        return queryset.order_by('-started_at')[:limit]