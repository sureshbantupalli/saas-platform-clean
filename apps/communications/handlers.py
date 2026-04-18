"""
Signal receivers for the Communications module.

Listens to system events from other modules and calls handle_event().
This module receives events — it never imports domain logic from the emitting modules.
"""
from django.dispatch import receiver

from apps.payments.signals import payment_failed, payment_success
from apps.payments.models import Payment

from apps.communications.services.communication_service import handle_event


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_payment_payload(payment: Payment) -> dict:
    return {
        "payment_id":      str(payment.id),
        "amount":          str(payment.amount),
        "reference_type":  payment.reference_type or "",
        "reference_id":    str(payment.reference_id) if payment.reference_id else "",
        "payment_method":  payment.payment_method or "",
        "gateway":         payment.gateway or "",
    }


def _enrich_with_member(payload: dict, payment: Payment) -> None:
    """Add member + membership fields to the payload when reference_type == 'membership'."""
    if payment.reference_type != "membership" or not payment.reference_id:
        return
    try:
        from apps.memberships.models import Membership
        membership = (
            Membership.base_objects
            .select_related("member", "plan")
            .get(pk=payment.reference_id)
        )
        member = membership.member
        payload.update({
            "member_name":      getattr(member, "name", "") or "",
            "phone":            getattr(member, "phone", "") or "",
            "email":            getattr(member, "email", "") or "",
            "membership_type":  membership.plan.name if membership.plan else "",
            "membership_id":    str(membership.pk),
        })
    except Exception:
        pass  # enrichment is best-effort; missing data is handled by renderer (blank)


# ── Receivers ─────────────────────────────────────────────────────────────────

@receiver(payment_success, sender=Payment)
def on_payment_success(sender, payment, **kwargs):
    payload = _base_payment_payload(payment)
    _enrich_with_member(payload, payment)
    handle_event("payment_success", payload, payment.tenant)


@receiver(payment_failed, sender=Payment)
def on_payment_failed(sender, payment, **kwargs):
    payload = _base_payment_payload(payment)
    _enrich_with_member(payload, payment)
    handle_event("payment_failed", payload, payment.tenant)


# ── Membership events ─────────────────────────────────────────────────────────

def _membership_payload(membership) -> dict:
    """Build a generic payload from a Membership instance."""
    member = getattr(membership, "member", None)
    plan   = getattr(membership, "plan", None)
    return {
        "membership_id":   str(membership.pk),
        "reference_type":  "membership",
        "reference_id":    str(membership.pk),
        "plan_name":       plan.name if plan else "",
        "member_name":     getattr(member, "name", "") or "",
        "phone":           getattr(member, "phone", "") or "",
        "email":           getattr(member, "email", "") or "",
        "start_date":      str(membership.start_date) if membership.start_date else "",
        "end_date":        str(membership.end_date) if membership.end_date else "",
        "remaining_sessions": str(membership.remaining_sessions or ""),
    }


def on_membership_activated(sender, membership, **kwargs):
    """
    Receives membership_activated signal. Defined at module level so Django's
    weak-reference signal mechanism doesn't garbage-collect it.
    """
    from apps.memberships.models import Membership
    try:
        fresh = Membership.base_objects.select_related("member", "plan").get(pk=membership.pk)
    except Membership.DoesNotExist:
        return
    payload = _membership_payload(fresh)
    handle_event("membership_activated", payload, fresh.tenant)


def _register_membership_receiver():
    """
    Late-bind to membership_activated after all apps are loaded (called from ready()).
    Uses weak=False + dispatch_uid to be safe against duplicate registration.
    """
    from apps.memberships.signals import membership_activated
    from apps.memberships.models import Membership
    membership_activated.connect(
        on_membership_activated,
        sender=Membership,
        weak=False,
        dispatch_uid="comms.on_membership_activated",
    )
