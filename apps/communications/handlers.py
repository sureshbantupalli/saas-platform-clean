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
