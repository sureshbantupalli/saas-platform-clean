from django.dispatch import Signal

# Fired after a Membership transitions to "active" status and the DB commit is confirmed.
# Sender: Membership model class. Kwargs: membership (Membership instance).
membership_activated = Signal()
