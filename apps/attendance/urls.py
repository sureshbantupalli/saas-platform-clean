from django.urls import path
from .views import BulkAttendanceAPIView

urlpatterns = [
    path("bulk/", BulkAttendanceAPIView.as_view(), name="bulk-attendance"),
]