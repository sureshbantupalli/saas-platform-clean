from django.urls import path
from apps.bookings.api.views import (
    CreateBookingAPIView,
    ConfirmBookingAPI,
    ListBookingsAPI,
    BulkAttendanceAPIView,
)

urlpatterns = [
    path("", ListBookingsAPI.as_view(), name="list-bookings"),  # ✅ FIXED

    path("create/", CreateBookingAPIView.as_view(), name="create-booking"),

    path("<uuid:booking_id>/confirm/", ConfirmBookingAPI.as_view(), name="confirm-booking"),

    path("attendance/bulk/", BulkAttendanceAPIView.as_view(), name="bulk-attendance"),
]