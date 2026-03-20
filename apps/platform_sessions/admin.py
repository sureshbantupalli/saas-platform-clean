from django.contrib import admin
from .models import (
    SessionType,
    SessionInstance,
    Booking
)


@admin.register(SessionType)
class SessionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant")


@admin.register(SessionInstance)
class SessionInstanceAdmin(admin.ModelAdmin):
    list_display = ("session_type", "start_time", "end_time", "capacity", "tenant")


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("member", "session", "status", "tenant", "booked_at")