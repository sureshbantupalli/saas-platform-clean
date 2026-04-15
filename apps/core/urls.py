from django.urls import path
from .views import tenant_dashboard, member_create_ui   # ✅ ADD THIS

urlpatterns = [

    path(
        "dashboard/",
        tenant_dashboard,
        name="tenant_dashboard",
    ),

    path(
        "members/add/",
        member_create_ui,
        name="member_create_ui"
    ),

]