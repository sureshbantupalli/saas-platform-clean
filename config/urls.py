"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.urls import reverse_lazy

# Custom Auth Views
from apps.accounts.views import login_view, logout_view
from apps.analytics.views import dashboard_api as analytics_dashboard_api

# Test Views
from apps.core.views import test_create_member, view_member
from apps.core.views_test import test_ui

# DRF Router Setup
from rest_framework.routers import DefaultRouter
from members.api import MemberViewSet
from apps.memberships.views import MembershipViewSet


# ==========================
# DRF Router
# ==========================

router = DefaultRouter()
router.register(r"members", MemberViewSet, basename="api-members")
router.register(r"memberships", MembershipViewSet, basename="api-memberships")


# ==========================
# URL Patterns
# ==========================

urlpatterns = [

    # Root → Monitoring Dashboard
    path(
        "",
        RedirectView.as_view(
            url=reverse_lazy("monitoring:lifecycle_dashboard"),
            permanent=False
        ),
        name="root_redirect"
    ),

    # Core Dashboard
    path(
        "",
        include("apps.core.urls")
    ),

    # Monitoring App
    path(
        "monitoring/",
        include("apps.monitoring.urls")
    ),

    # Test UI
    path(
        "test-ui/",
        test_ui
    ),

    # Django Admin
    path(
        "admin/",
        admin.site.urls
    ),

    # Authentication
    path(
        "login/",
        login_view,
        name="login"
    ),

    path(
        "logout/",
        logout_view,
        name="logout"
    ),

    # CRM Module
    path(
        "crm/",
        include("crm.urls")
    ),

    # Platform Control Layer
    path(
        "platform/",
        include("platform_core.urls")
    ),

    # Members (HTML App)
    path(
        "members/",
        include(("members.urls", "members"), namespace="members")
    ),

    # Memberships (HTML UI)
    path(
        "memberships/",
        include("apps.memberships.urls")
    ),

    # RBAC Test Endpoint
    path(
        "test-create/",
        test_create_member,
        name="test_create_member"
    ),

    # Scoped Member View Test
    path(
        "members/<uuid:member_id>/",
        view_member,
        name="view_member"
    ),

    # Authority / RBAC
    path(
        "authority/",
        include("apps.authority.urls")
    ),

    # ==========================
    # API Layer (DRF)
    # ==========================

    path(
        "api/",
        include(router.urls)
    ),

    # Dashboard Widgets API
    path(
        "api/dashboard/",
        include("apps.dashboard.api.urls")
    ),

    # ==========================
    # Bookings UI
    # ==========================

    path(
        "bookings/",
        include("apps.bookings.urls")
    ),

    # ==========================
    # Sessions UI
    # ==========================

    path(
        "sessions/",
        include("apps.sessions.urls")
    ),

    # ==========================
    # Booking APIs
    # ==========================

    path(
        "api/bookings/",
        include("apps.bookings.api.urls")
    ),

    # ==========================
    # ✅ Attendance APIs (DRF + UI APIs)
    # ==========================

    path(
        "api/attendance/",
        include("apps.attendance.urls")
    ),

    # ==========================
    # ✅ Attendance UI Routes
    # ==========================

    path(
        "attendance/",
        include("apps.attendance.urls")
    ),

    # ==========================
    # Intake Forms (UI + API)
    # ==========================

    path(
        "intake/",
        include(("apps.intake.urls", "intake"), namespace="intake")
    ),

    path(
        "api/intake/",
        include("apps.intake.api.urls")
    ),

    # ==========================
    # Payments (UI + API)
    # ==========================
    path(
        "payments/",
        include(("apps.payments.urls", "payments"), namespace="payments")
    ),
    path(
        "api/payments/",
        include("apps.payments.api.urls")
    ),

    # ==========================
    # Communications
    # ==========================
    path(
        "communications/",
        include(("apps.communications.urls", "communications"), namespace="communications")
    ),

    # ==========================
    # Analytics
    # ==========================
    path(
        "analytics/",
        include(("apps.analytics.urls", "analytics"), namespace="analytics")
    ),

    # ==========================
    # Next Best Actions
    # ==========================
    path(
        "api/actions/",
        include(("apps.actions.urls", "actions"), namespace="actions")
    ),
    path(
        "api/analytics/dashboard/",
        analytics_dashboard_api,
        name="api_analytics_dashboard",
    ),
]