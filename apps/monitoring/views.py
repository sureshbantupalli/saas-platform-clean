from django.shortcuts import render
from apps.core.permissions import require_permission
from .services.health_service import LifecycleHealthService


@require_permission("monitoring", "view")
def lifecycle_dashboard(request):
    summary = LifecycleHealthService.get_dashboard_summary()
    trend = LifecycleHealthService.get_trend_data()
    recent = LifecycleHealthService.get_recent_runs()

    return render(request, "monitoring/lifecycle_dashboard.html", {
        "summary": summary,
        "trend": trend,
        "recent": recent,
    })