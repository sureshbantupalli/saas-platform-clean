from django.contrib import admin

from .models import (
    SessionType,
    SessionTemplate,
    SessionSchedule,
    SessionInstance,
    Booking,
    Attendance,
)

from apps.sessions.services.booking_service import cancel_booking


@admin.register(SessionType)
class SessionTypeAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "allow_external_booking",
        "is_one_to_one",
        "created_at",
    )

    search_fields = (
        "name",
    )


@admin.register(SessionTemplate)
class SessionTemplateAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "session_type",
        "duration_minutes",
        "capacity",
        "is_active",
    )

    list_filter = (
        "session_type",
        "is_active",
    )

    search_fields = (
        "name",
    )


@admin.register(SessionSchedule)
class SessionScheduleAdmin(admin.ModelAdmin):

    list_display = (
        "template",
        "day_of_week",
        "start_time",
        "start_date",
        "end_date",
        "is_active",
    )

    list_filter = (
        "day_of_week",
        "is_active",
    )

    search_fields = (
        "template__name",
    )


@admin.register(SessionInstance)
class SessionInstanceAdmin(admin.ModelAdmin):

    list_display = (
        "schedule",
        "session_date",
        "start_time",
        "capacity",
        "status",
    )

    list_filter = (
        "status",
        "session_date",
    )

    search_fields = (
        "schedule__template__name",
    )


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):

    list_display = (
        "session_instance",
        "member",
        "guest_name",
        "booking_source",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "booking_source",
    )

    search_fields = (
        "member__email",
        "guest_name",
    )

    def save_model(self, request, obj, form, change):

        # Only check when editing existing record
        if change:

            old_booking = Booking.objects.get(pk=obj.pk)

            # Detect cancellation
            if (
                old_booking.status == Booking.STATUS_BOOKED
                and obj.status == Booking.STATUS_CANCELLED
            ):
                cancel_booking(booking=obj)
                return

        super().save_model(request, obj, form, change)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):

    list_display = (
        "session_instance",
        "member",
        "guest_name",
        "status",
        "attendance_source",
        "marked_at",
    )

    list_filter = (
        "status",
        "attendance_source",
    )

    search_fields = (
        "member__email",
        "guest_name",
    )