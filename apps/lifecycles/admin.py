from django.contrib import admin
from .models import LifecycleRun


@admin.register(LifecycleRun)
class LifecycleRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "started_at",
        "completed_at",
        "duration_ms",
        "total_checked",
        "total_updated",
        "total_errors",
        "status",
        "triggered_by",
    )

    list_filter = ("status", "triggered_by", "started_at")
    readonly_fields = (
        "started_at",
        "completed_at",
        "duration_ms",
        "total_checked",
        "total_updated",
        "total_errors",
        "status",
        "triggered_by",
        "notes",
    )

    ordering = ("-started_at",)