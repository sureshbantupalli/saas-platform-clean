import uuid
from django.db import models
from apps.core.models import TenantAwareModel
from apps.platform_sessions.models import SessionInstance
from apps.core.models import Tenant
from members.models import Member


class Booking(TenantAwareModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        WAITLISTED = "WAITLISTED", "Waitlisted"

    # ✅ Override tenant to avoid reverse accessor clash
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="new_bookings"
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    session = models.ForeignKey(
        SessionInstance,
        on_delete=models.CASCADE,
        related_name="booking_entries"
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="bookings"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    booking_date = models.DateField()
    booking_time = models.TimeField(null=True, blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bookings"