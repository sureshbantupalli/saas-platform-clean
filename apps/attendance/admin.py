from django.contrib import admin
from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "attendance_type",
        "member",
        "staff",
        "session_date",
        "status",
    )