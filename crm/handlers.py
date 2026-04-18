"""
CRM Signal Handlers

Listens to cross-module events and creates FollowUp records automatically.
Every significant member event can trigger a proactive follow-up task.
"""
import logging
from datetime import timedelta

from django.dispatch import receiver
from django.utils import timezone

from apps.payments.signals import payment_failed
from apps.payments.models import Payment
from apps.bookings.signals import booking_confirmed, session_missed
from apps.bookings.models import Booking

logger = logging.getLogger("crm.handlers")


def _resolve_member_from_payment(payment: Payment):
    if payment.reference_type != "membership" or not payment.reference_id:
        return None
    try:
        from apps.memberships.models import Membership
        return Membership.base_objects.select_related("member").get(
            pk=payment.reference_id
        ).member
    except Exception:
        return None


@receiver(payment_failed, sender=Payment)
def on_payment_failed(sender, payment, **kwargs):
    """Payment failed → create a same-day call follow-up for recovery."""
    member = _resolve_member_from_payment(payment)
    if not member:
        return
    try:
        from crm.services.followup_service import FollowUpService
        from crm.models import FollowUp
        FollowUpService.create_for_member(
            member         = member,
            tenant         = payment.tenant,
            followup_type  = FollowUp.TYPE_CALL,
            due_date       = timezone.now().date(),
            notes          = f"Payment of ₹{payment.amount} failed — contact for recovery.",
            reference_type = "payment",
            reference_id   = str(payment.id),
        )
    except Exception:
        logger.exception("CRM: follow-up creation failed for payment_failed %s", payment.pk)


@receiver(booking_confirmed, sender=Booking)
def on_booking_confirmed(sender, booking, member, session, tenant, **kwargs):
    """Booking confirmed → schedule a post-session check-in follow-up."""
    try:
        from crm.services.followup_service import FollowUpService
        from crm.models import FollowUp
        session_date  = session.start_time.date()
        followup_date = session_date + timedelta(days=1)
        FollowUpService.create_for_member(
            member         = member,
            tenant         = tenant,
            followup_type  = FollowUp.TYPE_CALL,
            due_date       = followup_date,
            notes          = f"Post-session check-in after {session.session_type.name} on {session_date}.",
            reference_type = "booking",
            reference_id   = str(booking.id),
        )
    except Exception:
        logger.exception("CRM: follow-up creation failed for booking_confirmed %s", booking.pk)


@receiver(session_missed, sender=Booking)
def on_session_missed(sender, booking, member, session, tenant, **kwargs):
    """Session missed → create an immediate re-engagement follow-up."""
    try:
        from crm.services.followup_service import FollowUpService
        from crm.models import FollowUp
        FollowUpService.create_for_member(
            member         = member,
            tenant         = tenant,
            followup_type  = FollowUp.TYPE_CALL,
            due_date       = timezone.now().date(),
            notes          = f"Missed {session.session_type.name} on {session.start_time.date()} — re-engage.",
            reference_type = "session_missed",
            reference_id   = str(booking.id),
        )
    except Exception:
        logger.exception("CRM: follow-up creation failed for session_missed %s", booking.pk)
