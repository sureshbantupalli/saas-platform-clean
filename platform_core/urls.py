from django.urls import path
from .views import PlatformDashboardView, TenantListView, ToggleTenantStatusView

app_name = "platform"

urlpatterns = [
    path("dashboard/", PlatformDashboardView.as_view(), name="dashboard"),
    path("tenants/", TenantListView.as_view(), name="tenants"),
    path("tenants/<uuid:tenant_id>/toggle/", ToggleTenantStatusView.as_view(), name="toggle_tenant_status"),
]