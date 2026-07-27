import json
from itertools import groupby

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.analytics.services.dashboard_service import get_dashboard_summary
from apps.actions.services.next_best_action_service import get_next_actions

_PRIORITY_META = {
    "HIGH":   {"label": "🔥 Urgent", "cls": "danger"},
    "MEDIUM": {"label": "⚠ Today",  "cls": "warning"},
    "LOW":    {"label": "ℹ Info",   "cls": "info"},
}


def _group_actions(actions: list) -> list:
    groups = []
    for priority, group in groupby(actions, key=lambda a: a["priority"]):
        meta = _PRIORITY_META.get(priority, {"label": priority, "cls": "secondary"})
        groups.append({**meta, "priority": priority, "actions": list(group)})
    return groups


@login_required
def dashboard_view(request):
    from apps.payments.services.payment_intelligence_service import get_payment_metrics

    data         = get_dashboard_summary(request.tenant)
    next_actions = get_next_actions(request.tenant)
    ctx = {
        "data":                  data,
        "next_actions":          next_actions,
        "next_action_groups":    _group_actions(next_actions),
        "revenue_trend_json":    json.dumps(data["charts"]["revenue_trend"]),
        "attendance_trend_json": json.dumps(data["charts"]["attendance_trend"]),
        "lead_funnel_json":      json.dumps(data["charts"]["lead_funnel"]),
        "payment_metrics":       get_payment_metrics(request.tenant),
    }
    return render(request, "analytics/dashboard.html", ctx)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_api(request):
    data = get_dashboard_summary(request.tenant)
    data["next_actions"] = get_next_actions(request.tenant)
    return Response(data)
