from django.shortcuts import render, get_object_or_404, redirect

from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import (
    SessionTemplate,
    SessionSchedule,
    SessionInstance,
    Booking,
    Attendance
)

from .forms import SessionTemplateForm

from apps.sessions.services.utilization_service import (
    get_tenant_session_dashboard,
    get_session_performance_dashboard,
    get_peak_day_demand,
    get_peak_time_demand,
    get_underutilized_sessions,
    get_schedule_optimization_suggestions
)


# ============================================================
# HTML UI Views
# ============================================================

def session_templates_list(request):

    templates = SessionTemplate.objects.filter(is_active=True)

    context = {
        "templates": templates
    }

    return render(request, "sessions/session_templates.html", context)


def session_schedules_list(request):

    schedules = SessionSchedule.objects.select_related("template")

    context = {
        "schedules": schedules
    }

    return render(request, "sessions/session_schedules.html", context)


def session_calendar(request):

    instances = SessionInstance.objects.select_related(
        "schedule",
        "schedule__template"
    ).order_by("session_date")

    context = {
        "instances": instances
    }

    return render(request, "sessions/session_calendar.html", context)


def session_instance_detail(request, instance_id):

    instance = get_object_or_404(SessionInstance, id=instance_id)

    bookings = Booking.objects.filter(session_instance=instance)

    attendance = Attendance.objects.filter(session_instance=instance)

    context = {
        "instance": instance,
        "bookings": bookings,
        "attendance": attendance,
    }

    return render(
        request,
        "sessions/session_instance_detail.html",
        context
    )


# ============================================================
# Reusable List Layout Engine
# ============================================================

def sessions_list_view(request):

    templates = SessionTemplate.objects.all()

    rows = []

    for t in templates:

        rows.append([
            f'<a href="/sessions/detail/{t.id}/">{t.name}</a>',
            t.session_type.name,
            t.capacity,
            t.is_active
        ])

    context = {

        "title": "Sessions",

        "columns": [
            "Session Name",
            "Type",
            "Capacity",
            "Active"
        ],

        "rows": rows
    }

    return render(
        request,
        "layouts/list_layout.html",
        context
    )


# ============================================================
# Reusable Detail Layout Engine
# ============================================================

def session_detail_view(request, template_id):

    template = get_object_or_404(
        SessionTemplate,
        id=template_id
    )

    fields = [

        ("Session Name", template.name),
        ("Session Type", template.session_type.name),
        ("Capacity", template.capacity),
        ("Active", template.is_active),

    ]

    context = {

        "title": "Session Detail",
        "fields": fields,

        "edit_url": f"/sessions/edit/{template.id}/",
        "delete_url": f"/sessions/delete/{template.id}/"

    }

    return render(
        request,
        "layouts/detail_layout.html",
        context
    )


# ============================================================
# Create Session (Form Layout Engine)
# ============================================================

def create_session_view(request):

    if request.method == "POST":

        form = SessionTemplateForm(request.POST)

        if form.is_valid():
            form.save()

            return redirect("/sessions/list/")

    else:

        form = SessionTemplateForm()

    context = {

        "title": "Create Session",
        "form": form

    }

    return render(
        request,
        "layouts/form_layout.html",
        context
    )


# ============================================================
# Edit Session (Form Layout Engine)
# ============================================================

def edit_session_view(request, template_id):

    template = get_object_or_404(
        SessionTemplate,
        id=template_id
    )

    if request.method == "POST":

        form = SessionTemplateForm(
            request.POST,
            instance=template
        )

        if form.is_valid():

            form.save()

            return redirect("/sessions/list/")

    else:

        form = SessionTemplateForm(instance=template)

    context = {

        "title": "Edit Session",
        "form": form

    }

    return render(
        request,
        "layouts/form_layout.html",
        context
    )

def delete_session_view(request, template_id):

    template = get_object_or_404(
        SessionTemplate,
        id=template_id
    )

    template.delete()

    return redirect("/sessions/list/")


# ============================================================
# Dashboard APIs
# ============================================================

@api_view(["GET"])
def tenant_session_dashboard(request):
    """
    Tenant dashboard analytics API
    """

    data = get_tenant_session_dashboard()

    return Response(data)


@api_view(["GET"])
def session_performance_dashboard(request):
    """
    API endpoint for session performance analytics
    """

    data = get_session_performance_dashboard()

    return Response(data)


@api_view(["GET"])
def peak_day_demand_dashboard(request):
    """
    API endpoint for peak day demand analytics
    """

    data = get_peak_day_demand()

    return Response(data)


@api_view(["GET"])
def peak_time_demand_dashboard(request):
    """
    API endpoint for peak time demand analytics
    """

    data = get_peak_time_demand()

    return Response(data)


@api_view(["GET"])
def underutilized_sessions_dashboard(request):
    """
    API endpoint for detecting underutilized sessions
    """

    data = get_underutilized_sessions()

    return Response(data)


@api_view(["GET"])
def schedule_optimization_dashboard(request):
    """
    API endpoint for schedule optimization suggestions
    """

    data = get_schedule_optimization_suggestions()

    return Response(data)