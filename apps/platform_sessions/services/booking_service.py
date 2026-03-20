from django.db import transaction
from django.core.exceptions import ValidationError
from apps.platform_sessions.models import Booking


class BookingService:

    @staticmethod
    @transaction.atomic
    def create_booking(member, session):

        # Prevent duplicate booking
        if Booking.objects.filter(member=member, session=session).exists():
            raise ValidationError("Already booked")

        # Check capacity
        if session.capacity:
            current_count = Booking.objects.filter(
                session=session,
                status=Booking.Status.BOOKED
            ).count()

            if current_count >= session.capacity:
                raise ValidationError("Session is full")

        return Booking.objects.create(
            member=member,
            session=session
        )