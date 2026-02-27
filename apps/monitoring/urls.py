from django.urls import path
from .views import lifecycle_dashboard

urlpatterns = [
    path("lifecycle-health/", lifecycle_dashboard, name="lifecycle_dashboard"),
]