import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.analytics.services.dashboard_service import get_dashboard_summary
from apps.actions.services.next_best_action_service import get_next_actions


@login_required
def dashboard_view(request):
    data = get_dashboard_summary(request.tenant)
    next_actions = get_next_actions(request.tenant)
    ctx = {
        "data":                  data,
        "next_actions":          next_actions,
        "revenue_trend_json":    json.dumps(data["charts"]["revenue_trend"]),
        "attendance_trend_json": json.dumps(data["charts"]["attendance_trend"]),
        "lead_funnel_json":      json.dumps(data["charts"]["lead_funnel"]),
    }
    return render(request, "analytics/dashboard.html", ctx)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_api(request):
    data = get_dashboard_summary(request.tenant)
    data["next_actions"] = get_next_actions(request.tenant)
    return Response(data)
