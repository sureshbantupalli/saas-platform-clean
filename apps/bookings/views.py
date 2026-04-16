from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from apps.bookings.models import Booking
from apps.bookings.services.booking_service import create_booking, cancel_booking
from apps.platform_sessions.models import SessionInstance
from members.models import Member


@login_required
def booking_list(request):
    tenant = request.user.tenant

    bookings = (
        Booking.base_objects
        .filter(tenant=tenant)
        .select_related("member", "session__session_type")
        .order_by("-created_at")
    )

    sessions = (
        SessionInstance.base_objects
        .filter(tenant=tenant)
        .select_related("session_type")
        .order_by("start_time")
    )

    members = (
        Member.base_objects
        .filter(tenant=tenant, is_deleted=False)
        .order_by("first_name")
    )

    context = {
        "bookings": bookings,
        "sessions": sessions,
        "members": members,
    }
    return render(request, "bookings/booking_list.html", context)


@login_required
def booking_create(request):
    if request.method != "POST":
        return redirect("bookings:booking_list")

    tenant = request.user.tenant
    member_id = request.POST.get("member_id")
    schedule_id = request.POST.get("schedule_id")

    try:
        booking = create_booking(
            tenant=tenant,
            data={"member_id": member_id, "schedule_id": schedule_id}
        )
        messages.success(request, f"Booking created — Status: {booking.get_status_display()}")
    except Exception as e:
        messages.error(request, str(e))

    return redirect("bookings:booking_list")


@login_required
def booking_cancel(request, booking_id):
    if request.method != "POST":
        return redirect("bookings:booking_list")

    tenant = request.user.tenant
    booking = get_object_or_404(Booking.base_objects, id=booking_id, tenant=tenant)

    if booking.status == Booking.Status.CANCELLED:
        messages.warning(request, "Booking is already cancelled.")
        return redirect("bookings:booking_list")

    try:
        cancel_booking(booking)
        messages.success(request, "Booking cancelled. Waitlisted members promoted if any.")
    except Exception as e:
        messages.error(request, str(e))

    return redirect("bookings:booking_list")
