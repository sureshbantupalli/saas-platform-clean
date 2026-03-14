from django.urls import path

from .views import DashboardWidgetsAPIView

urlpatterns = [
    path("widgets/", DashboardWidgetsAPIView.as_view(), name="dashboard-widgets"),
]