from django.db import transaction
from django.core.exceptions import ValidationError

from apps.sessions.models import Booking, SessionInstance


def _get_booked_count(*, tenant, session_instance):
    """
    Returns number of confirmed bookings.
    """
    return Booking.objects.filter(
        tenant=tenant,
        session_instance=session_instance,
        status=Booking.STATUS_BOOKED,
    ).count()


def _get_waitlist_count(*, tenant, session_instance):
    """
    Returns number of waitlisted bookings.
    """
    return Booking.objects.filter(
        tenant=tenant,
        session_instance=session_instance,
        status=Booking.STATUS_WAITLISTED,
    ).count()


def create_booking(
    *,
    tenant,
    session_instance,
    member=None,
    guest_name=None,
    booking_source=Booking.SOURCE_MEMBER,
    external_partner=None,
):
    """
    Central booking creation logic.

    Handles:
    - duplicate booking prevention
    - capacity enforcement
    - automatic waitlisting
    """

    if not member and not guest_name:
        raise ValidationError("Either member or guest_name must be provided.")

    with transaction.atomic():

        # Lock session row (prevents race conditions)
        session = (
            SessionInstance.objects
            .select_for_update()
            .get(id=session_instance.id)
        )

        # Prevent duplicate member booking
        if member:
            exists = Booking.objects.filter(
                tenant=tenant,
                session_instance=session,
                member=member,
            ).exists()

            if exists:
                raise ValidationError("Member already booked for this session.")

        booked_count = _get_booked_count(
            tenant=tenant,
            session_instance=session
        )

        # Determine booking status
        if booked_count < session.capacity:
            booking_status = Booking.STATUS_BOOKED
        else:
            booking_status = Booking.STATUS_WAITLISTED

        booking = Booking.objects.create(
            tenant=tenant,
            session_instance=session,
            member=member,
            guest_name=guest_name,
            booking_source=booking_source,
            external_partner=external_partner,
            status=booking_status,
        )

    return booking


def cancel_booking(*, booking):
    """
    Cancel a booking and promote waitlisted users automatically.
    """

    with transaction.atomic():

        session = (
            SessionInstance.objects
            .select_for_update()
            .get(id=booking.session_instance.id)
        )

        # Cancel the booking
        booking.status = Booking.STATUS_CANCELLED
        booking.save(update_fields=["status"])

        booked_count = _get_booked_count(
            tenant=booking.tenant,
            session_instance=session
        )

        # If seat available promote waitlist
        if booked_count < session.capacity:

            waitlisted = (
                Booking.objects
                .filter(
                    tenant=booking.tenant,
                    session_instance=session,
                    status=Booking.STATUS_WAITLISTED,
                )
                .order_by("created_at")
                .first()
            )

            if waitlisted:

                waitlisted.status = Booking.STATUS_BOOKED
                waitlisted.save(update_fields=["status"])

                return waitlisted

    return None