import uuid
from django.shortcuts import get_object_or_404
from django.db import transaction

from apps.bookings.models import Booking
from apps.platform_sessions.models import SessionInstance
from apps.attendance.models import Attendance
from members.models import Member


def create_booking(*, tenant, data):
    """
    FINAL BOOKING ENGINE:
    - Capacity aware
    - Waitlist support
    - Tenant safe
    """

    member_id = data.get("member_id")
    schedule_id = data.get("schedule_id")

    print("\n===== BOOKING DEBUG START =====")
    print("Incoming Tenant:", tenant)
    print("Member ID:", member_id)
    print("Schedule ID:", schedule_id)

    # ✅ Get Session (tenant-safe)
    session = get_object_or_404(
        SessionInstance,
        id=schedule_id,
        tenant_id=tenant.id
    )

    print("Session Found:", session.id, session.tenant_id)

    # ✅ Get Member
    member = get_object_or_404(
        Member,
        id=member_id,
        tenant_id=tenant.id
    )

    print("Member Found:", member.id, member.tenant_id)

    # 🚨 HARD VALIDATION
    if member.tenant_id != session.tenant_id:
        raise ValueError(
            f"Tenant mismatch: Member({member.tenant_id}) != Session({session.tenant_id})"
        )

    # ✅ Prevent duplicate booking
    if Booking.objects.filter(
        member_id=member.id,
        session_id=session.id,
        tenant_id=tenant.id
    ).exists():
        raise ValueError("Booking already exists")

    # 🔥 COUNT CONFIRMED BOOKINGS
    confirmed_count = Booking.objects.filter(
        session=session,
        tenant=tenant,
        status=Booking.Status.CONFIRMED
    ).count()

    print("Confirmed Count:", confirmed_count)
    print("Session Capacity:", session.capacity)

    # 🔥 DECIDE STATUS
    if confirmed_count < session.capacity:
        booking_status = Booking.Status.CONFIRMED
        print("✅ Booking CONFIRMED")
    else:
        booking_status = Booking.Status.WAITLISTED
        print("⏳ Booking WAITLISTED")

    # ✅ Extract date & time
    booking_date = session.start_time.date()
    booking_time = session.start_time.time()

    # ✅ Create booking
    booking = Booking.objects.create(
        tenant_id=tenant.id,
        member_id=member.id,
        session_id=session.id,   # 🔥 FIXED
        booking_date=booking_date,
        booking_time=booking_time,
        price=0,
        status=booking_status,
    )

    print("✅ Booking Created:", booking.id)
    print("===== BOOKING DEBUG END =====\n")

    return booking


def confirm_booking(booking: Booking):
    booking.status = Booking.Status.CONFIRMED
    booking.save()
    return booking


@transaction.atomic
def cancel_booking(booking: Booking):
    """
    Cancel booking + promote from waitlist
    """

    print("\n===== CANCEL BOOKING DEBUG =====")

    session = booking.session

    # ✅ Cancel current booking
    booking.status = Booking.Status.CANCELLED
    booking.save()

    print(f"❌ Booking Cancelled: {booking.id}")

    # 🔥 FIND NEXT WAITLISTED USER
    next_booking = Booking.objects.filter(
        session=session,
        tenant=booking.tenant,
        status=Booking.Status.WAITLISTED
    ).order_by("created_at").first()

    # 🔥 PROMOTE
    if next_booking:
        next_booking.status = Booking.Status.CONFIRMED
        next_booking.save()

        print(f"🚀 Promoted from waitlist: {next_booking.id}")
    else:
        print("No waitlisted users")

    print("===== END CANCEL DEBUG =====\n")

    return booking


def mark_bulk_attendance(*, tenant, booking_ids, status):

    booking_ids = [uuid.UUID(str(bid)) for bid in booking_ids]

    print("\n===== BULK ATTENDANCE DEBUG =====")
    print("Incoming booking_ids:", booking_ids)
    print("API Tenant:", tenant)

    bookings = Booking.objects.filter(
        id__in=booking_ids,
        tenant_id=tenant.id
    )

    print("Matched bookings:", bookings.count())

    if not bookings.exists():
        raise ValueError("No valid bookings found for this tenant.")

    bookings = list(bookings)

    for booking in bookings:
        Attendance.objects.create(
            tenant_id=tenant.id,
            booking=booking,
            member_id=booking.member_id,   # ✅ FIXED
            attendance_type="session",
            session_date=booking.session.start_time.date(),
            status=status
        )

    print("✅ Attendance created successfully")
    print("=================================\n")

    return True