from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Count, Q
from apps.lifecycles.models import LifecycleRun


class LifecycleHealthService:

    @staticmethod
    def get_dashboard_summary():
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)
        one_day_ago = now - timedelta(days=1)

        runs_7d = LifecycleRun.objects.filter(started_at__gte=seven_days_ago)
        runs_24h = LifecycleRun.objects.filter(started_at__gte=one_day_ago)

        last_run = LifecycleRun.objects.order_by('-started_at').first()

        return {
            "last_status": last_run.status if last_run else "N/A",
            "last_duration": last_run.duration_ms if last_run else 0,
            "runs_24h": runs_24h.count(),
            "failures_7d": runs_7d.filter(status=LifecycleRun.Status.FAILED).count(),
            "avg_duration_7d": runs_7d.aggregate(avg=Avg("duration_ms"))["avg"] or 0
        }

    @staticmethod
    def get_trend_data():
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)

        runs = (
            LifecycleRun.objects
            .filter(started_at__gte=seven_days_ago)
            .extra(select={'day': "date(started_at)"})
            .values('day')
            .annotate(
                total_runs=Count('id'),
                failures=Count('id', filter=Q(status=LifecycleRun.Status.FAILED)),
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

    @staticmethod
    def get_recent_runs(limit=20):
        return LifecycleRun.objects.order_by('-started_at')[:limit]