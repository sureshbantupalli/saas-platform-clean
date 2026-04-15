from django.urls import path

# APIs
from .api import BulkMarkAttendanceAPI, AttendanceHistoryAPI

# UI Views
from .views import (
    BulkAttendanceAPIView,
    attendance_ui,
    search_members,
    mark_attendance_ui,
    list_bookings,
    booking_detail,
    get_session_members,
)

urlpatterns = [

    # =====================================================
    # 🔥 CORE ATTENDANCE APIs
    # =====================================================
    path("bulk-mark/", BulkMarkAttendanceAPI.as_view(), name="bulk-attendance"),
    path("history/", AttendanceHistoryAPI.as_view(), name="attendance-history"),


    # =====================================================
    # 🖥️ UI ROUTES
    # =====================================================
    path("ui/", attendance_ui, name="attendance_ui"),


    # =====================================================
    # 🚶 WALK-IN APIs
    # =====================================================
    path("api/search-members/", search_members, name="search_members"),
    path("api/mark-attendance/", mark_attendance_ui, name="mark_attendance_ui"),


    # =====================================================
    # 📅 SESSION / BOOKING APIs
    # =====================================================
    path("api/bookings/", list_bookings, name="list_bookings"),
    path("api/bookings/<uuid:booking_id>/", booking_detail, name="booking_detail"),

    path(
        "api/sessions/<uuid:session_id>/members/",
        get_session_members,
        name="session_members"
    ),
]