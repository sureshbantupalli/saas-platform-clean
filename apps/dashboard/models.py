from django.db import models
from apps.core.models import TenantAwareModel


class Dashboard(TenantAwareModel):
    """
    Represents a dashboard configuration for a tenant.
    """

    name = models.CharField(max_length=255)

    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.tenant} - {self.name}"


class DashboardWidget(TenantAwareModel):
    """
    Represents a widget placed on a dashboard.
    """

    dashboard = models.ForeignKey(
        Dashboard,
        on_delete=models.CASCADE,
        related_name="widgets"
    )

    widget_key = models.CharField(
        max_length=100,
        help_text="Identifier of the widget (today_sessions, attendance_today, etc)"
    )

    position = models.PositiveIntegerField(
        help_text="Widget order on dashboard"
    )

    width = models.PositiveIntegerField(default=4)

    height = models.PositiveIntegerField(default=2)

    config = models.JSONField(
        blank=True,
        null=True,
        help_text="Optional widget configuration"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.dashboard} - {self.widget_key}"