import uuid
import logging

from django.shortcuts import get_object_or_404
from django.db import transaction

from apps.bookings.models import Booking
from apps.platform_sessions.models import SessionInstance
from apps.attendance.models import Attendance
from members.models import Member

logger = logging.getLogger(__name__)


def create_booking(*, tenant, data):
    """
    Create a booking for a member in a session.
    Automatically assigns CONFIRMED or WAITLISTED status based on capacity.
    """

    member_id = data.get("member_id")
    schedule_id = data.get("schedule_id")

    session = get_object_or_404(SessionInstance, id=schedule_id, tenant_id=tenant.id)
    member = get_object_or_404(Member, id=member_id, tenant_id=tenant.id)

    if member.tenant_id != session.tenant_id:
        raise ValueError(
            f"Tenant mismatch: member belongs to {member.tenant_id}, "
            f"session belongs to {session.tenant_id}"
        )

    if Booking.objects.filter(
        member_id=member.id,
        session_id=session.id,
        tenant_id=tenant.id
    ).exists():
        raise ValueError("Booking already exists for this member and session.")

    confirmed_count = Booking.objects.filter(
        session=session,
        tenant=tenant,
        status=Booking.Status.CONFIRMED
    ).count()

    if confirmed_count < session.capacity:
        booking_status = Booking.Status.CONFIRMED
    else:
        booking_status = Booking.Status.WAITLISTED

    booking = Booking.objects.create(
        tenant_id=tenant.id,
        member_id=member.id,
        session_id=session.id,
        booking_date=session.start_time.date(),
        booking_time=session.start_time.time(),
        price=0,
        status=booking_status,
    )

    logger.info(
        "Booking created: booking=%s member=%s session=%s status=%s",
        booking.id, member.id, session.id, booking_status
    )

    return booking


def confirm_booking(booking: Booking):
    booking.status = Booking.Status.CONFIRMED
    booking.save()
    return booking


@transaction.atomic
def cancel_booking(booking: Booking):
    """
    Cancel a booking and promote the earliest waitlisted member if one exists.
    """

    session = booking.session

    booking.status = Booking.Status.CANCELLED
    booking.save()

    logger.info("Booking cancelled: %s", booking.id)

    next_booking = (
        Booking.objects
        .filter(session=session, tenant=booking.tenant, status=Booking.Status.WAITLISTED)
        .order_by("created_at")
        .first()
    )

    if next_booking:
        next_booking.status = Booking.Status.CONFIRMED
        next_booking.save()
        logger.info("Promoted from waitlist: %s", next_booking.id)

    return booking


def mark_bulk_attendance(*, tenant, booking_ids, status):

    booking_ids = [uuid.UUID(str(bid)) for bid in booking_ids]

    bookings = Booking.objects.filter(id__in=booking_ids, tenant_id=tenant.id)

    if not bookings.exists():
        raise ValueError("No valid bookings found for this tenant.")

    bookings = list(bookings)

    for booking in bookings:
        Attendance.objects.create(
            tenant_id=tenant.id,
            booking=booking,
            member_id=booking.member_id,
            attendance_type="session",
            session_date=booking.session.start_time.date(),
            status=status,
        )

    logger.info("Bulk attendance marked: %d records, status=%s", len(bookings), status)

    return True
