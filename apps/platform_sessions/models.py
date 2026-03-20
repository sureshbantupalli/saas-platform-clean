import uuid
from django.db import models
from apps.core.models import TenantAwareModel, Tenant


class SessionType(TenantAwareModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class SessionInstance(TenantAwareModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.CASCADE,
        related_name="instances"
    )

    # ✅ Using DateTime (correct for real-world scheduling)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    capacity = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.session_type} ({self.start_time})"


class Booking(TenantAwareModel):

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="legacy_bookings"
    )

    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    member = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="legacy_session_bookings"
    )

    session = models.ForeignKey(
        SessionInstance,
        on_delete=models.CASCADE,
        related_name="legacy_bookings"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )

    booked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member} → {self.session}"