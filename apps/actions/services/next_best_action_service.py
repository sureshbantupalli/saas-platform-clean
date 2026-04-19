from datetime import date, timedelta

from django.db.models import Count, ExpressionWrapper, F, FloatField, Min, Q, Subquery

PRIORITY_HIGH   = "HIGH"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_LOW    = "LOW"

_PRIORITY_ORDER = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}

LOW_UTILIZATION_THRESHOLD = 0.30

_QUICK_ACTIONS = {
    "followup_overdue": [
        {"type": "call",      "label": "Call Now"},
        {"type": "mark_done", "label": "Mark Done"},
    ],
    "hot_leads_not_contacted": [
        {"type": "call",           "label": "Call Now"},
        {"type": "send_whatsapp",  "label": "Send Reminder"},
    ],
    "followup_due_today": [
        {"type": "call",      "label": "Call Now"},
        {"type": "mark_done", "label": "Mark Done"},
    ],
    "expiring_memberships": [
        {"type": "send_whatsapp", "label": "Send Reminder"},
    ],
    "at_risk_members": [
        {"type": "call",          "label": "Call Now"},
        {"type": "send_whatsapp", "label": "Send Reminder"},
    ],
    "low_utilization_slots": [],
    "payment_pending": [
        {"type": "send_reminder", "label": "Send Reminder"},
    ],
}


def get_next_actions(tenant) -> list[dict]:
    today = date.today()
    rules = [
        _followup_overdue,
        _hot_leads_not_contacted,
        _followup_due_today,
        _expiring_memberships,
        _at_risk_members,
        _low_utilization_slots,
        _payment_pending,
    ]
    actions = []
    for rule in rules:
        action = rule(tenant, today)
        if action and action["count"] > 0:
            actions.append(action)

    actions.sort(key=lambda a: (_PRIORITY_ORDER[a["priority"]], -a["count"]))
    return actions


# ── Rule A ────────────────────────────────────────────────────────────────────

def _followup_overdue(tenant, today: date) -> dict:
    from crm.models import FollowUp
    qs = FollowUp.objects.filter(
        tenant=tenant,
        status=FollowUp.STATUS_PENDING,
        due_date__lt=today,
    )
    count = qs.count()
    urgency = "Overdue"
    if count:
        oldest = qs.aggregate(oldest=Min("due_date"))["oldest"]
        urgency = f"Oldest overdue by {(today - oldest).days} day(s)"
    return {
        "type":          "followup_overdue",
        "priority":      PRIORITY_HIGH,
        "title":         "Call overdue leads",
        "count":         count,
        "cta_url":       "/crm/followups/",
        "cta_label":     "View Queue",
        "urgency":       urgency,
        "quick_actions": _QUICK_ACTIONS["followup_overdue"],
        "description":   f"{count} follow-up(s) are past their due date.",
    }


# ── Rule B ────────────────────────────────────────────────────────────────────

def _hot_leads_not_contacted(tenant, today: date) -> dict:
    from crm.models import Enquiry, EnquiryActivity
    two_days_ago = today - timedelta(days=2)

    recently_touched = (
        EnquiryActivity.objects.filter(
            tenant=tenant,
            created_at__date__gte=two_days_ago,
        )
        .exclude(action_type__in=["CREATED", "FOLLOWUP_SCHEDULED"])
        .values("enquiry_id")
        .distinct()
    )

    count = (
        Enquiry.objects.filter(
            tenant=tenant,
            next_followup_date__lt=today,
            converted_member__isnull=True,
        )
        .exclude(current_stage__is_loss_stage=True)
        .exclude(id__in=recently_touched)
        .count()
    )
    return {
        "type":          "hot_leads_not_contacted",
        "priority":      PRIORITY_HIGH,
        "title":         "Contact hot leads immediately",
        "count":         count,
        "cta_url":       "/crm/",
        "cta_label":     "View Leads",
        "urgency":       "Not contacted in 2+ days",
        "quick_actions": _QUICK_ACTIONS["hot_leads_not_contacted"],
        "description":   f"{count} high-priority lead(s) have not been contacted in 2+ days.",
    }


# ── Rule C ────────────────────────────────────────────────────────────────────

def _followup_due_today(tenant, today: date) -> dict:
    from crm.models import FollowUp
    count = FollowUp.objects.filter(
        tenant=tenant,
        status=FollowUp.STATUS_PENDING,
        due_date=today,
    ).count()
    return {
        "type":          "followup_due_today",
        "priority":      PRIORITY_MEDIUM,
        "title":         "Complete today's follow-ups",
        "count":         count,
        "cta_url":       "/crm/followups/",
        "cta_label":     "View Queue",
        "urgency":       "Due today",
        "quick_actions": _QUICK_ACTIONS["followup_due_today"],
        "description":   f"{count} follow-up(s) are scheduled for today.",
    }


# ── Rule D ────────────────────────────────────────────────────────────────────

def _expiring_memberships(tenant, today: date) -> dict:
    from apps.memberships.models import Membership
    in_7_days = today + timedelta(days=7)
    qs = Membership.base_objects.filter(
        tenant=tenant,
        status="active",
        end_date__gte=today,
        end_date__lte=in_7_days,
        is_deleted=False,
    )
    count = qs.count()
    urgency = "Expiring within 7 days"
    if count:
        soonest = qs.aggregate(soonest=Min("end_date"))["soonest"]
        urgency = f"Earliest expires in {(soonest - today).days} day(s)"
    return {
        "type":          "expiring_memberships",
        "priority":      PRIORITY_HIGH,
        "title":         "Renew expiring memberships",
        "count":         count,
        "cta_url":       "/members/?expiring=1",
        "cta_label":     "View Members",
        "urgency":       urgency,
        "quick_actions": _QUICK_ACTIONS["expiring_memberships"],
        "description":   f"{count} membership(s) expire within 7 days.",
    }


# ── Rule E ────────────────────────────────────────────────────────────────────

def _at_risk_members(tenant, today: date) -> dict:
    from apps.attendance.models import Attendance
    from apps.memberships.models import Membership
    from django.db.models import Count as DjCount

    seven_days_ago   = today - timedelta(days=7)
    fourteen_days_ago = today - timedelta(days=14)

    active_ids = list(
        Membership.base_objects.filter(
            tenant=tenant, status="active", is_deleted=False,
        )
        .values_list("member_id", flat=True)
        .distinct()
    )

    if not active_ids:
        return {
            "type": "at_risk_members", "priority": PRIORITY_HIGH,
            "title": "Re-engage at-risk members", "count": 0,
            "cta_url": "/members/?filter=at_risk", "cta_label": "View Members",
            "urgency": "No active members",
            "quick_actions": _QUICK_ACTIONS["at_risk_members"],
            "description": "0 active member(s) are at risk.",
        }

    recent = dict(
        Attendance.base_objects.filter(
            tenant=tenant, status="present",
            session_date__gte=seven_days_ago,
            is_deleted=False, member_id__in=active_ids,
        )
        .values("member_id")
        .annotate(cnt=DjCount("id"))
        .values_list("member_id", "cnt")
    )
    prev = dict(
        Attendance.base_objects.filter(
            tenant=tenant, status="present",
            session_date__gte=fourteen_days_ago,
            session_date__lt=seven_days_ago,
            is_deleted=False, member_id__in=active_ids,
        )
        .values("member_id")
        .annotate(cnt=DjCount("id"))
        .values_list("member_id", "cnt")
    )

    count = sum(
        1 for mid in active_ids
        if recent.get(mid, 0) == 0
        or (prev.get(mid, 0) > 0 and recent.get(mid, 0) < prev.get(mid, 0) * 0.5)
    )

    return {
        "type":          "at_risk_members",
        "priority":      PRIORITY_HIGH,
        "title":         "Re-engage at-risk members",
        "count":         count,
        "cta_url":       "/members/?filter=at_risk",
        "cta_label":     "View Members",
        "urgency":       "No or reduced activity in 7 days",
        "quick_actions": _QUICK_ACTIONS["at_risk_members"],
        "description":   f"{count} active member(s) are at risk.",
    }


# ── Rule F ────────────────────────────────────────────────────────────────────

def _low_utilization_slots(tenant, today: date) -> dict:
    from apps.sessions.models import SessionInstance
    in_7_days = today + timedelta(days=7)

    count = (
        SessionInstance.base_objects.filter(
            tenant=tenant,
            session_date__gte=today,
            session_date__lte=in_7_days,
            status=SessionInstance.STATUS_SCHEDULED,
            capacity__gt=0,
        )
        .annotate(
            booked=Count(
                "bookings",
                filter=Q(bookings__status__in=["booked", "attended"]),
            )
        )
        .filter(
            booked__lt=ExpressionWrapper(
                F("capacity") * LOW_UTILIZATION_THRESHOLD,
                output_field=FloatField(),
            )
        )
        .count()
    )
    return {
        "type":          "low_utilization_slots",
        "priority":      PRIORITY_MEDIUM,
        "title":         "Promote under-booked sessions",
        "count":         count,
        "cta_url":       "/sessions/dashboard/underutilized-sessions/",
        "cta_label":     "View Sessions",
        "urgency":       "Below 30% capacity",
        "quick_actions": _QUICK_ACTIONS["low_utilization_slots"],
        "description":   f"{count} session(s) in the next 7 days are below 30% capacity.",
    }


# ── Rule G ────────────────────────────────────────────────────────────────────

def _payment_pending(tenant, today: date) -> dict:
    from apps.memberships.models import Membership
    count = Membership.base_objects.filter(
        tenant=tenant,
        payment_status__in=["unpaid", "partial"],
        status__in=["active", "pending"],
        is_deleted=False,
    ).count()
    return {
        "type":          "payment_pending",
        "priority":      PRIORITY_HIGH,
        "title":         "Collect outstanding payments",
        "count":         count,
        "cta_url":       "/payments/?status=PENDING",
        "cta_label":     "View Payments",
        "urgency":       "Payment outstanding",
        "quick_actions": _QUICK_ACTIONS["payment_pending"],
        "description":   f"{count} membership(s) have outstanding payments.",
    }
