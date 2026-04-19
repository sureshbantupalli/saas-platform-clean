from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    MembershipViewSet,
    MembershipCreateView,
    membership_detail,
    plan_list,
    plan_create,
    plan_edit,
    plan_toggle_active,
)


router = DefaultRouter()
router.register(r"memberships", MembershipViewSet, basename="membership")


urlpatterns = [

    # Membership assignment (member → plan)
    path("add/", MembershipCreateView.as_view(), name="membership_add"),

    # Membership detail (financial breakdown)
    path("<uuid:pk>/", membership_detail, name="membership_detail"),

    # Membership Plan CRUD
    path("plans/", plan_list, name="plan_list"),
    path("plans/create/", plan_create, name="plan_create"),
    path("plans/<uuid:pk>/edit/", plan_edit, name="plan_edit"),
    path("plans/<uuid:pk>/toggle/", plan_toggle_active, name="plan_toggle_active"),

]

# API Routes
urlpatterns += router.urls
