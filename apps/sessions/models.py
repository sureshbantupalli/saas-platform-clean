import uuid
from django.db import models
from apps.core.models import TenantAwareModel


class SessionType(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(max_length=100)

    description = models.TextField(blank=True)

    allow_external_booking = models.BooleanField(default=False)

    is_one_to_one = models.BooleanField(default=False)

    # 🔥 NEW: Pricing Field
    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class SessionTemplate(TenantAwareModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.PROTECT,
        related_name="templates"
    )

    name = models.CharField(max_length=200)

    description = models.TextField(blank=True, null=True)

    duration_minutes = models.PositiveIntegerField()

    capacity = models.PositiveIntegerField(default=20)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class SessionSchedule(TenantAwareModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    template = models.ForeignKey(
        SessionTemplate,
        on_delete=models.CASCADE,
        related_name="schedules"
    )

    day_of_week = models.IntegerField(
        choices=[
            (1, "Monday"),
            (2, "Tuesday"),
            (3, "Wednesday"),
            (4, "Thursday"),
            (5, "Friday"),
            (6, "Saturday"),
            (7, "Sunday"),
        ]
    )

    start_time = models.TimeField()

    start_date = models.DateField()

    end_date = models.DateField(blank=True, null=True)

    capacity_override = models.PositiveIntegerField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.template.name} - {self.get_day_of_week_display()} {self.start_time}"


class SessionInstance(TenantAwareModel):

    STATUS_SCHEDULED = "scheduled"
    STATUS_CANCELLED = "cancelled"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_COMPLETED, "Completed"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    schedule = models.ForeignKey(
        SessionSchedule,
        on_delete=models.CASCADE,
        related_name="instances"
    )

    session_date = models.DateField()

    start_time = models.TimeField()

    capacity = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_SCHEDULED
    )

    instructor_override = models.UUIDField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("schedule", "session_date", "start_time")

    def __str__(self):
        return f"{self.schedule.template.name} - {self.session_date} {self.start_time}"


class Booking(TenantAwareModel):

    STATUS_BOOKED = "booked"
    STATUS_WAITLISTED = "waitlisted"
    STATUS_CANCELLED = "cancelled"
    STATUS_ATTENDED = "attended"
    STATUS_NO_SHOW = "no_show"

    STATUS_CHOICES = [
        (STATUS_BOOKED, "Booked"),
        (STATUS_WAITLISTED, "Waitlisted"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_ATTENDED, "Attended"),
        (STATUS_NO_SHOW, "No Show"),
    ]

    SOURCE_MEMBER = "member_portal"
    SOURCE_FRONT_DESK = "front_desk"
    SOURCE_WALK_IN = "walk_in"
    SOURCE_EXTERNAL = "external_partner"

    SOURCE_CHOICES = [
        (SOURCE_MEMBER, "Member Portal"),
        (SOURCE_FRONT_DESK, "Front Desk"),
        (SOURCE_WALK_IN, "Walk In"),
        (SOURCE_EXTERNAL, "External Partner"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    session_instance = models.ForeignKey(
        SessionInstance,
        on_delete=models.CASCADE,
        related_name="bookings"
    )

    member = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="session_bookings",
        null=True,
        blank=True
    )

    guest_name = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    booking_source = models.CharField(
        max_length=50,
        choices=SOURCE_CHOICES,
        default=SOURCE_MEMBER
    )

    external_partner = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_BOOKED
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("session_instance", "member")

    def __str__(self):
        if self.member:
            return f"{self.member} - {self.session_instance}"
        return f"{self.guest_name} - {self.session_instance}"

    def save(self, *args, **kwargs):

        if self.status not in [
            Booking.STATUS_CANCELLED,
            Booking.STATUS_ATTENDED,
            Booking.STATUS_NO_SHOW,
        ]:

            booked_count = Booking.objects.filter(
                session_instance=self.session_instance,
                status=Booking.STATUS_BOOKED
            ).exclude(id=self.id).count()

            if booked_count < self.session_instance.capacity:
                self.status = Booking.STATUS_BOOKED
            else:
                self.status = Booking.STATUS_WAITLISTED

        super().save(*args, **kwargs)


class Attendance(TenantAwareModel):

    STATUS_PRESENT = "present"
    STATUS_ABSENT = "absent"

    STATUS_CHOICES = [
        (STATUS_PRESENT, "Present"),
        (STATUS_ABSENT, "Absent"),
    ]

    SOURCE_TRAINER = "trainer"
    SOURCE_ADMIN = "admin"
    SOURCE_MEMBER = "member"
    SOURCE_SYSTEM = "system"

    SOURCE_CHOICES = [
        (SOURCE_TRAINER, "Trainer"),
        (SOURCE_ADMIN, "Admin / Front Desk"),
        (SOURCE_MEMBER, "Member Self Check-In"),
        (SOURCE_SYSTEM, "System Auto"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    session_instance = models.ForeignKey(
        "SessionInstance",
        on_delete=models.CASCADE,
        related_name="attendances"
    )

    member = models.ForeignKey(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    guest_name = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PRESENT
    )

    attendance_source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_TRAINER
    )

    marked_by = models.UUIDField(blank=True, null=True)

    marked_at = models.DateTimeField(auto_now_add=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.member:
            return f"{self.member} - {self.session_instance}"
        return f"{self.guest_name} - {self.session_instance}"

    class Meta:
        unique_together = (
            "session_instance",
            "member",
        )