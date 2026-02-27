"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import path, include

# 🔥 Existing Test Views
from apps.core.views import test_create_member, view_member
from apps.core.views_test import test_ui

# 🔥 DRF Router Setup
from rest_framework.routers import DefaultRouter
from members.api import MemberViewSet
from apps.memberships.views import MembershipViewSet

# Create DRF router
router = DefaultRouter()
router.register(r"members", MemberViewSet, basename="api-members")
router.register(r"memberships", MembershipViewSet, basename="api-memberships")

urlpatterns = [

    # 🔵 Monitoring App
    path("monitoring/", include("apps.monitoring.urls")),

    # 🔵 Test UI
    path("test-ui/", test_ui),

    # 🔵 Admin
    path("admin/", admin.site.urls),

    # 🔵 HTML Members App (Template-Based)
    path("members/", include("members.urls")),

    # 🔐 RBAC Test Endpoint (Create Permission)
    path("test-create/", test_create_member, name="test_create_member"),

    # 🔐 Scoped View Test (OWN vs ANY)
    path("members/<uuid:member_id>/", view_member, name="view_member"),

    # 🔵 Authority URLs
    path("", include("apps.authority.urls")),

    # 🔵 DRF API Layer
    path("api/", include(router.urls)),
]