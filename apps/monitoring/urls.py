from django.urls import path
from .views import lifecycle_dashboard

app_name = "monitoring"

urlpatterns = [
    path("lifecycle-health/", lifecycle_dashboard, name="lifecycle_dashboard"),
]