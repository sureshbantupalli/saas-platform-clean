"""
Membership module signal receivers.

Listens to payment lifecycle events and updates membership financial state.
The payments module emits events; this module reacts — no coupling in the other direction.
"""
from decimal import Decimal

from django.db.models import Sum
from django.dispatch import receiver
from django.utils import timezone

from django.db import transaction

from apps.payments.signals import payment_success, payment_failed
from apps.payments.models import Payment, PaymentStatus


@receiver(payment_success, sender=Payment)
def on_payment_success(sender, payment, **kwargs):
    if payment.reference_type != "membership":
        return

    # Re-verify from DB before activating anything — never trust signal sender alone.
    # This guard ensures membership is activated ONLY when the payment is genuinely
    # SUCCESS in the database, not just because a signal was emitted.
    from apps.payments.models import Payment as _Payment
    try:
        live_payment = _Payment.base_objects.get(pk=payment.pk)
    except _Payment.DoesNotExist:
        return
    if live_payment.status != PaymentStatus.SUCCESS:
        return

    from apps.memberships.models import Membership

    try:
        membership = Membership.base_objects.get(pk=payment.reference_id)
    except Membership.DoesNotExist:
        return

    # Aggregate from DB (not from the in-memory payment object) so partial payments
    # accumulate correctly across multiple transactions.
    total_paid = (
        Payment.base_objects
        .filter(
            reference_type="membership",
            reference_id=membership.pk,
            status=PaymentStatus.SUCCESS,
            is_deleted=False,
        )
        .aggregate(total=Sum("amount"))["total"]
    ) or Decimal("0")

    if total_paid >= membership.fee_amount:
        new_payment_status = "paid"
        new_status = "active"
    elif total_paid > 0:
        new_payment_status = "partial"
        new_status = "pending"
    else:
        new_payment_status = "unpaid"
        new_status = "pending"

    update_fields = {
        "amount_paid":    total_paid,
        "payment_status": new_payment_status,
        "status":         new_status,
        "updated_at":     timezone.now(),
    }

    # Renewal: expired membership now fully paid — push dates forward from today
    # so the lifecycle engine re-activates it without creating a new membership.
    if new_status == "active" and membership.status == "expired":
        import datetime
        from dateutil.relativedelta import relativedelta
        today = datetime.date.today()
        plan  = membership.plan
        cycle = plan.billing_cycle_type
        n     = plan.billing_interval
        if cycle == "DAILY":
            new_end = today + datetime.timedelta(days=n)
        elif cycle == "WEEKLY":
            new_end = today + datetime.timedelta(weeks=n)
        elif cycle == "MONTHLY":
            new_end = today + relativedelta(months=n)
        elif cycle == "YEARLY":
            new_end = today + relativedelta(years=n)
        else:
            span    = (membership.end_date - membership.start_date).days if membership.end_date and membership.start_date else 30
            new_end = today + datetime.timedelta(days=span)
        update_fields["start_date"] = today
        update_fields["end_date"]   = new_end

    Membership.base_objects.filter(pk=membership.pk).update(**update_fields)

    if new_status == "active":
        fresh = Membership.base_objects.get(pk=membership.pk)
        from apps.memberships.signals import membership_activated
        transaction.on_commit(
            lambda: membership_activated.send(sender=Membership, membership=fresh)
        )


@receiver(payment_failed, sender=Payment)
def on_payment_failed(sender, payment, **kwargs):
    if payment.reference_type != "membership":
        return

    from apps.memberships.models import Membership

    try:
        membership = Membership.base_objects.get(pk=payment.reference_id)
    except Membership.DoesNotExist:
        return

    if membership.status == "pending" and membership.payment_status == "unpaid":
        Membership.base_objects.filter(pk=membership.pk).update(
            status="cancelled",
            updated_at=timezone.now(),
        )
