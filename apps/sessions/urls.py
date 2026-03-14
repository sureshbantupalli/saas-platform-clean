from django.urls import path

from .views import (

    # Existing UI views
    session_templates_list,
    session_schedules_list,
    session_calendar,
    session_instance_detail,

    # Layout engine views
    sessions_list_view,
    session_detail_view,
    create_session_view,
    edit_session_view,
    delete_session_view,

    # Dashboard API views
    tenant_session_dashboard,
    session_performance_dashboard,
    peak_day_demand_dashboard,
    peak_time_demand_dashboard,
    underutilized_sessions_dashboard,
    schedule_optimization_dashboard
)

urlpatterns = [

    # =========================================================
    # HTML UI
    # =========================================================

    path(
        "templates/",
        session_templates_list
    ),

    path(
        "schedules/",
        session_schedules_list
    ),

    path(
        "calendar/",
        session_calendar
    ),

    path(
        "instance/<uuid:instance_id>/",
        session_instance_detail
    ),

    # =========================================================
    # Reusable Layout Engine URLs
    # =========================================================

    path(
        "list/",
        sessions_list_view,
        name="sessions_list"
    ),

    path(
        "detail/<uuid:template_id>/",
        session_detail_view,
        name="session_detail"
    ),

    path(
        "create/",
        create_session_view,
        name="create_session"
    ),

    path(
        "edit/<uuid:template_id>/",
        edit_session_view,
        name="edit_session"
    ),

    path(
        "delete/<uuid:template_id>/",
        delete_session_view,
        name="delete_session"
    ),

    # =========================================================
    # Dashboard APIs
    # =========================================================

    path(
        "dashboard/session-metrics/",
        tenant_session_dashboard,
        name="tenant_session_dashboard"
    ),

    path(
        "dashboard/session-performance/",
        session_performance_dashboard,
        name="session_performance_dashboard"
    ),

    path(
        "dashboard/peak-day-demand/",
        peak_day_demand_dashboard,
        name="peak_day_demand_dashboard"
    ),

    path(
        "dashboard/peak-time-demand/",
        peak_time_demand_dashboard,
        name="peak_time_demand_dashboard"
    ),

    path(
        "dashboard/underutilized-sessions/",
        underutilized_sessions_dashboard,
        name="underutilized_sessions_dashboard"
    ),

    path(
        "dashboard/schedule-optimization/",
        schedule_optimization_dashboard,
        name="schedule_optimization_dashboard"
    ),
]