import uuid
from django.db import models
from apps.core.models import BaseModel
from members.models import Member
from apps.bookings.models import Booking
from django.contrib.auth import get_user_model

User = get_user_model()


class Attendance(BaseModel):
    ATTENDANCE_TYPE_CHOICES = [
        ("session", "Session Based"),
        ("walkin", "Walk-in"),
        ("staff", "Staff"),
        ("online", "Online Session"),
    ]

    STATUS_CHOICES = [
        ("present", "Present"),
        ("absent", "Absent"),
        ("no_show", "No Show"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Who is this attendance for
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attendances"
    )

    staff = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="staff_attendances"
    )

    # Context
    attendance_type = models.CharField(
        max_length=20,
        choices=ATTENDANCE_TYPE_CHOICES
    )

    booking = models.ForeignKey(
        Booking,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendances"
    )

    session_date = models.DateField()

    check_in_time = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="present"
    )

    # Who marked attendance
    marked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="marked_attendances"
    )

    # Online session support
    session_code = models.CharField(max_length=20, null=True, blank=True)

    # Geo validation (future ready)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ("member", "booking", "session_date")

    def __str__(self):
        return f"{self.attendance_type} - {self.session_date}"