from django.db import models
from django.utils import timezone


class LifecycleRun(models.Model):

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        PARTIAL = "PARTIAL", "Partial"
        FAILED = "FAILED", "Failed"

    class TriggerSource(models.TextChoices):
        SCHEDULER = "SCHEDULER", "Scheduler"
        MANUAL = "MANUAL", "Manual"

    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    total_checked = models.PositiveIntegerField(default=0)
    total_updated = models.PositiveIntegerField(default=0)
    total_errors = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )

    triggered_by = models.CharField(
        max_length=20,
        choices=TriggerSource.choices,
        default=TriggerSource.SCHEDULER,
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"LifecycleRun #{self.id} - {self.status}"