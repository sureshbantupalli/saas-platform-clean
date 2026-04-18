from django.dispatch import Signal

# Fired after a booking is confirmed (not waitlisted)
# kwargs: booking, member, session, tenant
booking_confirmed = Signal()

# Fired when bulk attendance is marked no_show for a booking
# kwargs: booking, member, session, tenant
session_missed = Signal()
