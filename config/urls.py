"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.urls import reverse_lazy

# 🔐 Custom Auth Views
from apps.accounts.views import login_view, logout_view

# 🔥 Existing Test Views
from apps.core.views import test_create_member, view_member
from apps.core.views_test import test_ui

# 🔥 DRF Router Setup
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

    # ======================================
    # Root → Monitoring Dashboard
    # ======================================

    path(
        "",
        RedirectView.as_view(
            url=reverse_lazy("monitoring:lifecycle_dashboard"),
            permanent=False
        ),
        name="root_redirect"
    ),

    # ======================================
    # Monitoring App
    # ======================================

    path(
        "monitoring/",
        include("apps.monitoring.urls")
    ),

    # ======================================
    # Test UI
    # ======================================

    path(
        "test-ui/",
        test_ui
    ),

    # ======================================
    # Django Admin
    # ======================================

    path(
        "admin/",
        admin.site.urls
    ),

    # ======================================
    # Authentication
    # ======================================

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

    # ======================================
    # CRM Module
    # ======================================

    path(
        "crm/",
        include("crm.urls")
    ),

    # ======================================
    # Platform Control Layer
    # ======================================

    path(
        "platform/",
        include("platform_core.urls")
    ),

    # ======================================
    # Members (HTML App)
    # ======================================

    path(
        "members/",
        include(("members.urls", "members"), namespace="members")
    ),

    # ======================================
    # Memberships (HTML UI)
    # ======================================

    path(
        "memberships/",
        include("apps.memberships.urls")
    ),

    # ======================================
    # RBAC Test Endpoint
    # ======================================

    path(
        "test-create/",
        test_create_member,
        name="test_create_member"
    ),

    # ======================================
    # Scoped Member View Test
    # ======================================

    path(
        "members/<uuid:member_id>/",
        view_member,
        name="view_member"
    ),

    # ======================================
    # Authority / RBAC
    # ======================================

    path(
        "authority/",
        include("apps.authority.urls")
    ),

    # ======================================
    # API Layer (DRF)
    # ======================================

    path(
        "api/",
        include(router.urls)
    ),

]