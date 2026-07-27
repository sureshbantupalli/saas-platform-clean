import uuid
import logging

from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import Booking
from apps.platform_sessions.models import SessionInstance
from apps.attendance.models import Attendance
from apps.memberships.models import Membership
from members.models import Member

logger = logging.getLogger(__name__)


def _booking_payload(booking, member, session):
    """Build the communication payload for a booking event."""
    return {
        "member_name":    f"{member.first_name} {member.last_name}",
        "phone":          member.phone or "",
        "email":          member.email or "",
        "session_date":   str(session.start_time.date()),
        "session_time":   session.start_time.strftime("%I:%M %p"),
        "session_type":   session.session_type.name,
        "booking_id":     str(booking.id),
        "booking_status": booking.status,
        "reference_type": "booking",
        "reference_id":   str(booking.id),
    }


@transaction.atomic
def create_booking(*, tenant, data):
    """
    Create a booking for a member in a session.
    Automatically assigns CONFIRMED or WAITLISTED status based on capacity.
    """

    member_id = data.get("member_id")
    schedule_id = data.get("schedule_id")

    session = get_object_or_404(SessionInstance.base_objects, id=schedule_id, tenant_id=tenant.id)
    member = get_object_or_404(Member, id=member_id, tenant_id=tenant.id)

    if member.tenant_id != session.tenant_id:
        raise ValueError(
            f"Tenant mismatch: member belongs to {member.tenant_id}, "
            f"session belongs to {session.tenant_id}"
        )

    # Membership validation: member must have an active, date-valid membership
    today = timezone.now().date()
    has_active_membership = Membership.base_objects.filter(
        member=member,
        tenant=tenant,
        status="active",
        start_date__lte=today,
        end_date__gte=today,
    ).exists()
    if not has_active_membership:
        raise ValueError("Member does not have an active membership for this period.")

    if Booking.base_objects.filter(
        member_id=member.id,
        session_id=session.id,
        tenant_id=tenant.id
    ).exists():
        raise ValueError("Booking already exists for this member and session.")

    # Lock confirmed bookings row to prevent race condition on capacity check
    confirmed_count = (
        Booking.base_objects
        .select_for_update()
        .filter(session=session, tenant=tenant, status=Booking.Status.CONFIRMED)
        .count()
    )

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

    # Emit only confirmed bookings — waitlisted members will get a message when promoted
    if booking_status == Booking.Status.CONFIRMED:
        payload = _booking_payload(booking, member, session)
        transaction.on_commit(
            lambda: _emit_booking_confirmed(payload, tenant)
        )

    # Audit — fires after commit so the log only reflects persisted state
    _t   = tenant
    _bid = str(booking.id)
    _mid = str(member.id)
    _sid = str(session.id)
    _bst = str(booking_status)
    transaction.on_commit(lambda: _audit_booking_created(
        tenant=_t, booking_id=_bid, member_id=_mid, session_id=_sid, status=_bst,
    ))

    return booking


def _emit_booking_confirmed(payload, tenant):
    try:
        from apps.communications.services.communication_service import handle_event
        handle_event("booking_confirmed", payload, tenant)
    except Exception:
        logger.exception("Failed to emit booking_confirmed event")
    try:
        from apps.bookings.signals import booking_confirmed as _sig
        from apps.bookings.models import Booking as _B
        from apps.platform_sessions.models import SessionInstance as _SI
        from members.models import Member as _M
        booking = _B.base_objects.get(pk=payload["booking_id"])
        _sig.send(
            sender=_B,
            booking=booking,
            member=booking.member,
            session=booking.session,
            tenant=tenant,
        )
    except Exception:
        logger.exception("Failed to fire booking_confirmed signal")


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

    _old_status = booking.status
    booking.status = Booking.Status.CANCELLED
    booking.save()

    logger.info("Booking cancelled: %s", booking.id)

    # Audit the cancellation — after commit
    _t   = booking.tenant
    _bid = str(booking.id)
    _old = str(_old_status)
    _new = str(Booking.Status.CANCELLED)
    transaction.on_commit(lambda: _audit_booking_updated(
        tenant=_t, booking_id=_bid,
        old_status=_old, new_status=_new, source='user',
    ))

    next_booking = (
        Booking.base_objects
        .filter(session=session, tenant=booking.tenant, status=Booking.Status.WAITLISTED)
        .order_by("created_at")
        .first()
    )

    if next_booking:
        next_booking.status = Booking.Status.CONFIRMED
        next_booking.save()
        logger.info("Promoted from waitlist: %s", next_booking.id)

        # Audit the waitlist promotion separately — it's a distinct event
        _nt  = next_booking.tenant
        _nbid = str(next_booking.id)
        transaction.on_commit(lambda: _audit_booking_updated(
            tenant=_nt, booking_id=_nbid,
            old_status=str(Booking.Status.WAITLISTED),
            new_status=str(Booking.Status.CONFIRMED),
            source='system',
        ))

    return booking


def mark_bulk_attendance(*, tenant, booking_ids, status):
    booking_ids = [uuid.UUID(str(bid)) for bid in booking_ids]

    bookings = (
        Booking.base_objects
        .filter(id__in=booking_ids, tenant_id=tenant.id)
        .select_related("member", "session__session_type")
    )

    if not bookings.exists():
        raise ValueError("No valid bookings found for this tenant.")

    bookings = list(bookings)

    for booking in bookings:
        attendance = Attendance.objects.create(
            tenant_id=tenant.id,
            booking=booking,
            member_id=booking.member_id,
            attendance_type="session",
            session_date=booking.session.start_time.date(),
            status=status,
        )
        _audit_attendance_marked(
            tenant=tenant,
            attendance_id=str(attendance.id),
            booking_id=str(booking.id),
            member_id=str(booking.member_id),
            session_id=str(booking.session_id),
            status=status,
        )

    logger.info("Bulk attendance marked: %d records, status=%s", len(bookings), status)

    # Emit events after all DB writes succeed
    _emit_bulk_attendance_events(tenant, bookings, status)

    return True


def _emit_bulk_attendance_events(tenant, bookings, status):
    try:
        from apps.communications.services.communication_service import handle_event
        for booking in bookings:
            member = booking.member
            session = booking.session
            base = {
                "member_name":  f"{member.first_name} {member.last_name}",
                "phone":        member.phone or "",
                "email":        member.email or "",
                "session_date": str(session.start_time.date()),
                "session_time": session.start_time.strftime("%I:%M %p"),
                "session_type": session.session_type.name,
                "booking_id":   str(booking.id),
                "reference_type": "booking",
                "reference_id": str(booking.id),
            }
            if status == "present":
                handle_event("attendance_marked", base, tenant)
            elif status == "no_show":
                handle_event("session_missed", base, tenant)
                try:
                    from apps.bookings.signals import session_missed as _sig
                    from apps.bookings.models import Booking as _B
                    _sig.send(
                        sender=_B,
                        booking=booking,
                        member=booking.member,
                        session=booking.session,
                        tenant=tenant,
                    )
                except Exception:
                    pass
    except Exception:
        logger.exception("Failed to emit bulk attendance events")


# ── Audit helpers ─────────────────────────────────────────────────────────────

def _audit_booking_created(*, tenant, booking_id, member_id, session_id, status):
    try:
        from apps.audit.services import log_booking_change
        log_booking_change(
            tenant=tenant,
            action='create',
            field_name='status',
            new_value=status,
            metadata={
                'booking_id': booking_id,
                'member_id':  member_id,
                'session_id': session_id,
            },
        )
    except Exception:
        pass


def _audit_booking_updated(*, tenant, booking_id, old_status, new_status, source):
    try:
        from apps.audit.services import log_booking_change
        log_booking_change(
            tenant=tenant,
            action='update',
            source=source,
            field_name='status',
            old_value=old_status,
            new_value=new_status,
            metadata={'booking_id': booking_id},
        )
    except Exception:
        pass


def _audit_attendance_marked(*, tenant, attendance_id, booking_id, member_id, session_id, status):
    try:
        from apps.audit.services import log_attendance_change
        log_attendance_change(
            tenant=tenant,
            action='create',
            field_name='status',
            new_value=status,
            metadata={
                'attendance_id': attendance_id,
                'booking_id':    booking_id,
                'member_id':     member_id,
                'session_id':    session_id,
            },
        )
    except Exception:
        pass
