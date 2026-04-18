"""
Member CRM Timeline

Aggregates activity from Payments, Bookings, Attendance, and Communication Logs
into a single chronological feed for display on the member detail page.

All imports are deferred (inside the function) to avoid circular imports since
`members` is a root-level app that is imported by many other apps.
"""
import datetime
import logging

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# How many items to fetch from each source before merging and slicing
_SOURCE_LIMIT = 30
# Final cap on the merged timeline
_TIMELINE_LIMIT = 60


def _make_aware(dt):
    """Make a naive datetime timezone-aware using the current timezone."""
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt)


def get_member_timeline(member, tenant):
    """
    Return a list of dicts, sorted latest-first, representing all activity
    for this member within this tenant.

    Each dict has:
        type        — "payment" | "booking" | "attendance" | "communication"
        icon        — Bootstrap Icons class
        color       — Bootstrap color name (success / danger / primary / …)
        title       — short headline
        subtitle    — secondary label
        detail      — extra context string
        timestamp   — timezone-aware datetime (for sorting)
        link        — URL string or None
    """
    items = []

    # ── 1. Payments ───────────────────────────────────────────────────────────
    try:
        from apps.payments.models import Payment, PaymentStatus
        membership_ids = list(member.memberships.values_list("id", flat=True))
        for p in (
            Payment.base_objects
            .filter(
                tenant=tenant,
                reference_type="membership",
                reference_id__in=membership_ids,
                is_deleted=False,
            )
            .order_by("-created_at")[:_SOURCE_LIMIT]
        ):
            if p.status == PaymentStatus.SUCCESS:
                color = "success"
            elif p.status == PaymentStatus.FAILED:
                color = "danger"
            else:
                color = "warning"

            method = p.payment_method or p.gateway or ""
            items.append({
                "type":      "payment",
                "icon":      "bi-credit-card",
                "color":     color,
                "title":     f"Payment ₹{p.amount}",
                "subtitle":  p.get_status_display(),
                "detail":    method.replace("_", " ").title() if method else "",
                "timestamp": p.created_at,
                "link":      None,
            })
    except Exception:
        logger.exception("Timeline: error loading payments for member %s", member.pk)

    # ── 2. Bookings ───────────────────────────────────────────────────────────
    try:
        from apps.bookings.models import Booking
        booking_qs = (
            Booking.base_objects
            .filter(tenant=tenant, member=member, is_deleted=False)
            .select_related("session__session_type")
            .order_by("-created_at")[:_SOURCE_LIMIT]
        )
        booking_ids = []
        for b in booking_qs:
            booking_ids.append(b.id)
            if b.status == Booking.Status.CONFIRMED:
                color = "primary"
            elif b.status == Booking.Status.WAITLISTED:
                color = "warning"
            elif b.status == Booking.Status.CANCELLED:
                color = "secondary"
            else:
                color = "light"

            time_str = b.booking_time.strftime("%I:%M %p") if b.booking_time else ""
            items.append({
                "type":      "booking",
                "icon":      "bi-bookmark-check",
                "color":     color,
                "title":     f"Booking — {b.session.session_type.name}",
                "subtitle":  b.get_status_display(),
                "detail":    f"{b.booking_date}  {time_str}".strip(),
                "timestamp": b.created_at,
                "link":      None,
            })
    except Exception:
        logger.exception("Timeline: error loading bookings for member %s", member.pk)
        booking_ids = []

    # ── 3. Attendance ─────────────────────────────────────────────────────────
    try:
        from apps.attendance.models import Attendance
        for a in (
            Attendance.base_objects
            .filter(tenant=tenant, member=member)
            .order_by("-session_date")[:_SOURCE_LIMIT]
        ):
            if a.status == "present":
                color, icon = "success", "bi-clipboard2-check"
            elif a.status == "no_show":
                color, icon = "danger",  "bi-clipboard2-x"
            else:
                color, icon = "warning", "bi-clipboard2-minus"

            ts = a.check_in_time or _make_aware(
                datetime.datetime.combine(a.session_date, datetime.time(23, 59))
            )
            items.append({
                "type":      "attendance",
                "icon":      icon,
                "color":     color,
                "title":     f"Attendance — {a.get_status_display()}",
                "subtitle":  a.get_attendance_type_display(),
                "detail":    str(a.session_date),
                "timestamp": ts,
                "link":      None,
            })
    except Exception:
        logger.exception("Timeline: error loading attendance for member %s", member.pk)

    # ── 4. Communication Logs ─────────────────────────────────────────────────
    try:
        from apps.communications.models import CommunicationLog, MessageStatus

        # Match logs by reference_id (membership or booking) OR by phone/email
        ref_ids = (
            [str(mid) for mid in membership_ids]
            + [str(bid) for bid in booking_ids]
        )
        q = Q(tenant=tenant, reference_id__in=ref_ids)
        if member.phone:
            q |= Q(tenant=tenant, recipient=member.phone)
        if member.email:
            q |= Q(tenant=tenant, recipient=str(member.email))

        for cl in (
            CommunicationLog.base_objects
            .filter(q)
            .order_by("-created_at")[:_SOURCE_LIMIT]
        ):
            color = "info" if cl.status == MessageStatus.SENT else "secondary"
            ch_label = cl.get_channel_display()
            items.append({
                "type":      "communication",
                "icon":      "bi-chat-dots",
                "color":     color,
                "title":     f"{ch_label} sent",
                "subtitle":  cl.get_status_display(),
                "detail":    cl.message[:120],
                "timestamp": cl.created_at,
                "link":      None,
            })
    except Exception:
        logger.exception("Timeline: error loading comms logs for member %s", member.pk)

    # ── Sort and cap ──────────────────────────────────────────────────────────
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return items[:_TIMELINE_LIMIT]
