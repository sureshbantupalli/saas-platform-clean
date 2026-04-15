import uuid
from django.db import models
from django.core.exceptions import ValidationError
from apps.core.models import TenantAwareModel, Tenant
from members.models import Member
from apps.bookings.models import Booking
from django.contrib.auth import get_user_model

User = get_user_model()


class Attendance(TenantAwareModel):

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

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="attendances"
    )

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

    attendance_type = models.CharField(
        max_length=20,
        choices=ATTENDANCE_TYPE_CHOICES
    )

    # ✅ IMPORTANT: booking optional (for walk-in)
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

    marked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="marked_attendances"
    )

    session_code = models.CharField(max_length=20, null=True, blank=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ("member", "booking", "session_date")

    def __str__(self):
        return f"{self.attendance_type} - {self.session_date}"

    # ==============================
    # ✅ VALIDATION (UPDATED)
    # ==============================
    def clean(self):
        from apps.memberships.models import Membership

        # ✅ Enforce booking only for session-based attendance
        if self.attendance_type == "session" and not self.booking:
            raise ValidationError({
                "__all__": "Booking is required for session-based attendance."
            })

        # Only validate for present members
        if self.status != "present" or not self.member:
            return

        membership = Membership.objects.filter(
            member_id=self.member.id,
            status="active"
        ).order_by("-start_date").first()

        if not membership:
            return

        # ✅ Only check session limits for CLASS_PACK
        if membership.plan.plan_type == "CLASS_PACK":
            if membership.remaining_sessions is None or membership.remaining_sessions <= 0:
                raise ValidationError({
                    "__all__": "No remaining sessions. Cannot mark attendance."
                })

    # ==============================
    # 🔥 CORE LOGIC (UNCHANGED)
    # ==============================
    def save(self, *args, **kwargs):
        is_new = not Attendance.objects.filter(pk=self.pk).exists()

        # ✅ Call clean() before saving (IMPORTANT)
        self.clean()

        super().save(*args, **kwargs)

        # Only process for new attendance
        if not is_new:
            return

        # Only for present members
        if self.status != "present" or not self.member:
            return

        from apps.memberships.models import Membership

        membership = Membership.objects.filter(
            member_id=self.member.id,
            status="active"
        ).order_by("-start_date").first()

        print("========== DEBUG ==========")
        print("Attendance Member:", self.member)
        print("Membership Found:", membership)

        if not membership:
            print("No active membership found")
            print("===========================")
            return

        print("Remaining BEFORE:", membership.remaining_sessions)

        # ✅ ONLY apply to CLASS_PACK
        if membership.plan.plan_type == "CLASS_PACK":
            if membership.remaining_sessions is not None and membership.remaining_sessions > 0:
                membership.remaining_sessions -= 1
                membership.save()

                print("Remaining AFTER:", membership.remaining_sessions)

        print("===========================")