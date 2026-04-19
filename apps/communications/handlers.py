"""
Signal receivers for the Communications module.

Listens to system events from other modules and calls handle_event().
All payloads are wrapped in CommunicationEvent to enforce the standard contract.
This module receives events — it never imports domain logic from the emitting modules.
"""
from django.dispatch import receiver

from apps.payments.signals import payment_failed, payment_success
from apps.payments.models import Payment

from apps.communications.services.communication_service import handle_event
from apps.communications.services.event_schema import CommunicationEvent


# ── Payment helpers ───────────────────────────────────────────────────────────

def _payment_data(payment: Payment) -> dict:
    return {
        "payment_id":     str(payment.id),
        "amount":         str(payment.amount),
        "reference_type": payment.reference_type or "",
        "reference_id":   str(payment.reference_id) if payment.reference_id else "",
        "payment_method": payment.payment_method or "",
        "gateway":        payment.gateway or "",
    }


def _enrich_with_member(data: dict, payment: Payment) -> None:
    """Add member + membership fields when reference_type == 'membership'."""
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
        data.update({
            "member_name":     getattr(member, "name", "") or "",
            "phone":           getattr(member, "phone", "") or "",
            "email":           getattr(member, "email", "") or "",
            "membership_type": membership.plan.name if membership.plan else "",
            "membership_id":   str(membership.pk),
        })
    except Exception:
        pass  # enrichment is best-effort; missing keys render as ""


# ── Payment receivers ─────────────────────────────────────────────────────────

@receiver(payment_success, sender=Payment)
def on_payment_success(sender, payment, **kwargs):
    data = _payment_data(payment)
    _enrich_with_member(data, payment)
    event = CommunicationEvent(
        event       = "payment_success",
        tenant_id   = str(payment.tenant_id),
        entity_type = "payment",
        entity_id   = str(payment.pk),
        data        = data,
    )
    handle_event(event.event, event.to_payload(), payment.tenant)


@receiver(payment_failed, sender=Payment)
def on_payment_failed(sender, payment, **kwargs):
    data = _payment_data(payment)
    _enrich_with_member(data, payment)
    event = CommunicationEvent(
        event       = "payment_failed",
        tenant_id   = str(payment.tenant_id),
        entity_type = "payment",
        entity_id   = str(payment.pk),
        data        = data,
    )
    handle_event(event.event, event.to_payload(), payment.tenant)


# ── Membership events ─────────────────────────────────────────────────────────

def _membership_payload(membership) -> dict:
    """Generic data dict from a Membership instance — no business logic."""
    member = getattr(membership, "member", None)
    plan   = getattr(membership, "plan", None)
    return {
        "membership_id":      str(membership.pk),
        "reference_type":     "membership",
        "reference_id":       str(membership.pk),
        "plan_name":          plan.name if plan else "",
        "member_name":        getattr(member, "name", "") or "",
        "phone":              getattr(member, "phone", "") or "",
        "email":              getattr(member, "email", "") or "",
        "start_date":         str(membership.start_date) if membership.start_date else "",
        "end_date":           str(membership.end_date) if membership.end_date else "",
        "remaining_sessions": str(membership.remaining_sessions or ""),
    }


def on_membership_activated(sender, membership, **kwargs):
    """
    Receives membership_activated signal. Defined at module level so Django's
    weak-reference mechanism doesn't garbage-collect it.
    """
    from apps.memberships.models import Membership
    try:
        fresh = Membership.base_objects.select_related("member", "plan").get(pk=membership.pk)
    except Membership.DoesNotExist:
        return
    data  = _membership_payload(fresh)
    event = CommunicationEvent(
        event       = "membership_activated",
        tenant_id   = str(fresh.tenant_id),
        entity_type = "member",
        entity_id   = str(fresh.pk),
        data        = data,
    )
    handle_event(event.event, event.to_payload(), fresh.tenant)


def _register_membership_receiver():
    """
    Late-bind to membership_activated after all apps are loaded (called from ready()).
    Uses weak=False + dispatch_uid to avoid garbage-collection and duplicate registration.
    """
    from apps.memberships.signals import membership_activated
    from apps.memberships.models import Membership
    membership_activated.connect(
        on_membership_activated,
        sender=Membership,
        weak=False,
        dispatch_uid="comms.on_membership_activated",
    )
