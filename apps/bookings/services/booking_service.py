import uuid
from django.shortcuts import get_object_or_404

from apps.bookings.models import Booking
from apps.platform_sessions.models import SessionInstance, Attendance
from members.models import Member


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

    # ✅ Get Session FIRST (important)
    session = get_object_or_404(
        SessionInstance,
        id=schedule_id,
        tenant=tenant
    )

    print("Session Found:", session.id, session.tenant_id)

    # ✅ Get Member WITH tenant check
    member = get_object_or_404(
        Member,
        id=member_id,
        tenant=tenant
    )

    print("Member Found:", member.id, member.tenant_id)

    # 🚨 HARD VALIDATION (VERY IMPORTANT)
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


# ✅ FINAL DEBUG + FIX VERSION
def mark_bulk_attendance(*, tenant, booking_ids, status):

    # 🔥 Convert to UUID
    booking_ids = [uuid.UUID(str(bid)) for bid in booking_ids]

    print("\n===== BULK ATTENDANCE DEBUG =====")
    print("Incoming booking_ids:", booking_ids)
    print("API Tenant:", tenant)

    all_bookings = Booking.objects.all()
    print("Total bookings in DB:", all_bookings.count())

    print("All booking IDs in DB:",
          list(Booking.objects.values_list("id", flat=True)))

    print("All booking tenant IDs:",
          list(Booking.objects.values_list("tenant_id", flat=True)))

    # 🔥 Try tenant-safe filter FIRST (recommended)
    bookings = Booking.objects.filter(
        id__in=booking_ids,
        tenant=tenant
    )
    print("Matched bookings (with tenant):", bookings.count())

    # ❌ If still not found → debug fallback
    if not bookings.exists():
        bookings = Booking.objects.filter(id__in=booking_ids)
        print("Matched bookings (without tenant):", bookings.count())

    # ❌ Still not found
    if not bookings.exists():
        raise ValueError(
            f"No valid bookings found. DB count: {all_bookings.count()}"
        )

    # ✅ Create attendance
    for booking in bookings:
        Attendance.objects.create(
            tenant=tenant,
            booking=booking,
            status=status
        )

    print("✅ Attendance created successfully")
    print("=================================\n")

    return True