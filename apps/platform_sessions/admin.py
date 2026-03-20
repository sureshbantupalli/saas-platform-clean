from django.contrib import admin
from .models import (
    SessionType,
    SessionInstance,
    Attendance,
)

# ❌ REMOVE Booking from here (wrong app)


@admin.register(SessionType)
class SessionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant")


@admin.register(SessionInstance)
class SessionInstanceAdmin(admin.ModelAdmin):
    list_display = ("session_type", "start_time", "end_time", "capacity", "tenant")


# ❌ Booking removed from this app


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("booking", "status", "tenant", "marked_at")