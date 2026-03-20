import uuid
from django.shortcuts import get_object_or_404

from apps.bookings.models import Booking
from apps.platform_sessions.models import SessionInstance
from apps.attendance.models import Attendance
from members.models import Member
from datetime import date


def create_booking(*, tenant, data):
    """
    Final working booking logic aligned with your models
    """

    member_id = data.get("member_id")
    schedule_id = data.get("schedule_id")

    print("\n===== BOOKING DEBUG START =====")
    print("Incoming Tenant:", tenant)
    print("Member ID:", member_id)
    print("Schedule ID:", schedule_id)

    # ✅ Get Session FIRST
    session = get_object_or_404(
        SessionInstance,
        id=schedule_id,
        tenant=tenant
    )

    print("Session Found:", session.id, session.tenant_id)

    # ✅ Get Member
    member = get_object_or_404(
        Member,
        id=member_id,
        tenant=tenant
    )

    print("Member Found:", member.id, member.tenant_id)

    # 🚨 HARD VALIDATION
    if member.tenant_id != session.tenant_id:
        raise ValueError(
            f"Tenant mismatch: Member({member.tenant_id}) != Session({session.tenant_id})"
        )

    # ✅ Prevent duplicate booking
    if Booking.objects.filter(
        user_id=member.id,
        session=session,
        tenant=tenant
    ).exists():
        raise ValueError("Booking already exists")

    # ✅ Extract date & time
    booking_date = session.start_time.date()
    booking_time = session.start_time.time()

    # ✅ Create booking
    booking = Booking.objects.create(
        tenant=tenant,
        user_id=member.id,
        session=session,
        booking_date=booking_date,
        booking_time=booking_time,
        price=0,
        status=Booking.Status.CONFIRMED,
    )

    print("✅ Booking Created:", booking.id)
    print("===== BOOKING DEBUG END =====\n")

    return booking


def confirm_booking(booking: Booking):
    booking.status = Booking.Status.CONFIRMED
    booking.save()
    return booking


def cancel_booking(booking: Booking):
    booking.status = Booking.Status.CANCELLED
    booking.save()
    return booking


# ✅ FINAL FIXED VERSION (CLEAN)
def mark_bulk_attendance(*, tenant, booking_ids, status):

    # 🔥 Convert to UUID
    booking_ids = [uuid.UUID(str(bid)) for bid in booking_ids]

    print("\n===== BULK ATTENDANCE DEBUG =====")
    print("Incoming booking_ids:", booking_ids)
    print("API Tenant:", tenant)

    # ✅ Always use tenant-safe queryset
    bookings = Booking.objects.filter(
        id__in=booking_ids,
        tenant=tenant
    )

    print("Matched bookings:", bookings.count())

    if not bookings.exists():
        raise ValueError("No valid bookings found for this tenant.")

    # 🔥 CRITICAL FIX: ensure real model instances (no lazy issues)
    bookings = list(bookings)

    # ✅ Create attendance
    for booking in bookings:
        Attendance.objects.create(
            tenant=tenant,
            booking=booking,
            member_id=booking.user_id,              # ✅ important
            attendance_type="session",          # ✅ required
            session_date=booking.session.start_time.date(),  # ✅ BEST SOURCE
            status=status
        )

    print("✅ Attendance created successfully")
    print("=================================\n")

    return True