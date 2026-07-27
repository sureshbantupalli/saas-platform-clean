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


# Per-source fetch cap for the paginated API (higher than screen-only limit)
_API_SOURCE_LIMIT = 50
_API_PAGE_SIZE    = 20


def get_member_timeline_api(member, tenant, *, type_filter=None, page=1, page_size=_API_PAGE_SIZE):
    """
    Paginated, filterable, JSON-serialisable timeline for the member detail API.

    Returns a dict::

        {
            items:     list of serialised timeline entries,
            total:     int   — total items across all pages,
            has_more:  bool,
            page:      int,
            page_size: int,
        }

    Each item dict keys:
        type / icon / color / title / subtitle / detail / link / timestamp_iso
    """
    from django.urls import reverse, NoReverseMatch

    def _link(viewname, *args):
        try:
            return reverse(viewname, args=args)
        except NoReverseMatch:
            return None

    items         = []
    membership_ids: list = []
    booking_ids:   list = []
    include_all = not type_filter

    # ── 1. Payments ───────────────────────────────────────────────────────────
    if include_all or type_filter == "payment":
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
                .order_by("-created_at")[:_API_SOURCE_LIMIT]
            ):
                color = ("success" if p.status == PaymentStatus.SUCCESS
                         else "danger" if p.status == PaymentStatus.FAILED
                         else "warning")
                method = (p.payment_method or p.gateway or "").replace("_", " ").title()
                items.append({
                    "type":      "payment",
                    "icon":      "bi-credit-card",
                    "color":     color,
                    "title":     f"Payment ₹{p.amount}",
                    "subtitle":  p.get_status_display(),
                    "detail":    method,
                    "timestamp": p.created_at,
                    "link":      _link("payments:payment_detail", str(p.pk)),
                    "_key":      f"payment:{p.pk}:{p.created_at.isoformat()}",
                })
        except Exception:
            logger.exception("Timeline API: payments error for %s", member.pk)

    # ── 2. Bookings ───────────────────────────────────────────────────────────
    if include_all or type_filter == "booking":
        try:
            from apps.bookings.models import Booking
            booking_qs = (
                Booking.base_objects
                .filter(tenant=tenant, member=member, is_deleted=False)
                .select_related("session__session_type")
                .order_by("-created_at")[:_API_SOURCE_LIMIT]
            )
            for b in booking_qs:
                booking_ids.append(b.id)
                color = {
                    Booking.Status.CONFIRMED:  "primary",
                    Booking.Status.WAITLISTED: "warning",
                    Booking.Status.CANCELLED:  "secondary",
                }.get(b.status, "light")
                time_str = b.booking_time.strftime("%H:%M") if b.booking_time else ""
                items.append({
                    "type":      "booking",
                    "icon":      "bi-bookmark-check",
                    "color":     color,
                    "title":     f"Booking — {b.session.session_type.name}",
                    "subtitle":  b.get_status_display(),
                    "detail":    f"{b.booking_date} {time_str}".strip(),
                    "timestamp": b.created_at,
                    "link":      None,
                    "_key":      f"booking:{b.pk}:{b.created_at.isoformat()}",
                })
        except Exception:
            logger.exception("Timeline API: bookings error for %s", member.pk)

    # ── 3. Attendance ─────────────────────────────────────────────────────────
    if include_all or type_filter == "attendance":
        try:
            from apps.attendance.models import Attendance
            for a in (
                Attendance.base_objects
                .filter(tenant=tenant, member=member)
                .order_by("-session_date")[:_API_SOURCE_LIMIT]
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
                    "_key":      f"attendance:{a.pk}:{a.created_at.isoformat()}",
                })
        except Exception:
            logger.exception("Timeline API: attendance error for %s", member.pk)

    # ── 4. Communication Logs ─────────────────────────────────────────────────
    if include_all or type_filter == "communication":
        try:
            from apps.communications.models import CommunicationLog, MessageStatus
            from django.db.models import Q as _Q
            if not membership_ids:
                membership_ids = list(member.memberships.values_list("id", flat=True))
            ref_ids = (
                [str(mid) for mid in membership_ids]
                + [str(bid) for bid in booking_ids]
            )
            q = _Q(tenant=tenant, reference_id__in=ref_ids)
            if member.phone:
                q |= _Q(tenant=tenant, recipient=member.phone)
            if member.email:
                q |= _Q(tenant=tenant, recipient=str(member.email))
            for cl in (
                CommunicationLog.base_objects.filter(q).order_by("-created_at")[:_API_SOURCE_LIMIT]
            ):
                color = "info" if cl.status == MessageStatus.SENT else "secondary"
                items.append({
                    "type":      "communication",
                    "icon":      "bi-chat-dots",
                    "color":     color,
                    "title":     f"{cl.get_channel_display()} sent",
                    "subtitle":  cl.get_status_display(),
                    "detail":    cl.message[:120],
                    "timestamp": cl.created_at,
                    "link":      None,
                    "_key":      f"comm:{cl.pk}:{cl.created_at.isoformat()}",
                })
        except Exception:
            logger.exception("Timeline API: comms error for %s", member.pk)

    # ── 5. Enrollments (from Activity model) ──────────────────────────────────
    # Architectural direction: Activity is the future single source of truth for
    # the timeline.  Long-term goal is Timeline = Activity-only, with every other
    # model emitting an Activity row on write instead of being queried here directly.
    # The hybrid approach above (direct DB queries + Activity for enrollments) is
    # intentional for this transition phase — do not collapse it prematurely.
    #
    # Deduplication invariant: until the migration is complete, Activity is queried
    # ONLY for types that have NO direct DB source above (currently: ENROLLMENT).
    # When other ActivityType values (PAYMENT, DOCUMENT, …) are eventually emitted,
    # retire the corresponding direct query above rather than adding it here.
    if include_all or type_filter == "enrollment":
        try:
            from apps.activity.models import Activity, ActivityType
            for act in (
                Activity.base_objects
                .filter(
                    tenant=tenant,
                    person=member,
                    activity_type=ActivityType.ENROLLMENT,
                )
                .select_related("vertical")
                .order_by("-created_at")[:_API_SOURCE_LIMIT]
            ):
                items.append({
                    "type":      "enrollment",
                    "icon":      "bi-person-check",
                    "color":     "primary",
                    "title":     act.title,
                    "subtitle":  act.vertical.name if act.vertical_id else "",
                    "detail":    "",
                    "timestamp": act.created_at,
                    "link":      None,
                    "_key":      f"enrollment:{act.pk}:{act.created_at.isoformat()}",
                })
        except Exception:
            logger.exception("Timeline API: enrollments error for %s", member.pk)

    # ── Sort (UTC-normalised, stable), deduplicate, paginate, serialise ──────
    # Primary key: UTC timestamp — normalise so local-TZ datetimes (e.g. the
    # attendance check_in fallback) sort consistently with the UTC created_at
    # fields used by every other source.
    # Secondary key: _key string — acts as a deterministic tiebreaker when two
    # items share an identical timestamp, preventing reorder flicker across pages.
    # (Cursor-based pagination would eliminate this class of edge case entirely.
    # Migration trigger: switch when page > 10 is routinely reached OR any
    # tenant exceeds ~50 k rows across all timeline sources.  Below that
    # threshold the in-memory merge + offset approach is simpler and fast
    # enough.)
    from django.utils.timezone import utc as _utc

    def _sort_key(item):
        ts = item["timestamp"]
        utc_ts = ts.astimezone(_utc) if timezone.is_aware(ts) else timezone.make_aware(ts).astimezone(_utc)
        return (utc_ts, item.get("_key", ""))

    items.sort(key=_sort_key, reverse=True)

    # Runtime dedup — backs up the documented invariant in case a future source
    # accidentally emits the same logical event that another source already covers.
    # Key scheme: "type:pk:created_at_iso".
    #   - `type` namespaces across sources — payment:X never collides with booking:X.
    #   - `pk` is unique per model row (UUID); collision within a type is impossible.
    #   - `created_at_iso` is a safety net for future composite/non-PK sources where
    #     a natural primary key may not exist.  For current sources it is redundant.
    seen_keys: set = set()
    deduped: list = []
    for item in items:
        key = item.get("_key")
        if key:
            if key in seen_keys:
                continue
            seen_keys.add(key)
        deduped.append(item)

    total  = len(deduped)
    start  = (page - 1) * page_size
    end    = start + page_size
    result = []
    for item in deduped[start:end]:
        ts  = item["timestamp"]
        # Strip internal-only fields before sending to the client.
        row = {k: v for k, v in item.items() if k not in ("timestamp", "_key")}
        row["timestamp_iso"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        result.append(row)

    return {
        "items":     result,
        "total":     total,
        "has_more":  end < total,
        "page":      page,
        "page_size": page_size,
    }
