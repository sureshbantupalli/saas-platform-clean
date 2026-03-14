from django.db import transaction
from django.core.exceptions import ValidationError

from apps.sessions.models import Attendance, Booking
from apps.memberships.models import Membership, MembershipUsage

def mark_attendance(
    *,
    tenant,
    session_instance,
    member=None,
    guest_name=None,
    attendance_source=Attendance.SOURCE_TRAINER,
    marked_by=None,
):
    """
    Central attendance creation logic.

    Supports:
    - booked members
    - walk-ins
    - trainer marking
    - automatic membership usage deduction
    """

    if not member and not guest_name:
        raise ValidationError("Either member or guest_name must be provided.")

    with transaction.atomic():

        # Prevent duplicate attendance for member
        if member:
            existing = Attendance.objects.filter(
                tenant=tenant,
                session_instance=session_instance,
                member=member
            ).exists()

            if existing:
                raise ValidationError("Attendance already recorded for this member.")

        attendance = Attendance.objects.create(
            tenant=tenant,
            session_instance=session_instance,
            member=member,
            guest_name=guest_name,
            status=Attendance.STATUS_PRESENT,
            attendance_source=attendance_source,
            marked_by=marked_by
        )

        # Handle membership usage
        if member:

            membership = Membership.objects.filter(
                tenant=tenant,
                member=member,
                status="active"
            ).first()


            if membership:

                # Only deduct if membership has limited sessions
                if membership.remaining_sessions is not None:

                    if membership.remaining_sessions <= 0:
                        raise ValidationError("No remaining sessions in membership.")

                    MembershipUsage.objects.create(
                        tenant=tenant,
                        membership=membership,
                        session_instance=session_instance,
                        attendance=attendance
                    )

                    membership.remaining_sessions -= 1
                    membership.save(update_fields=["remaining_sessions"])

        return attendance