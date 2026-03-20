from apps.bookings.models import Booking


def get_bookings_by_user(*, tenant, user_id):
    return Booking.objects.filter(tenant=tenant, user_id=user_id)


def get_booking_by_id(*, tenant, booking_id):
    return Booking.objects.get(id=booking_id, tenant=tenant)