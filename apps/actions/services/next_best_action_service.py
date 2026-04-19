from datetime import date, timedelta

from django.db.models import Count, ExpressionWrapper, F, FloatField, Q, Subquery

PRIORITY_HIGH   = "HIGH"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_LOW    = "LOW"

_PRIORITY_ORDER = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}

LOW_UTILIZATION_THRESHOLD = 0.30


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
    count = FollowUp.objects.filter(
        tenant=tenant,
        status=FollowUp.STATUS_PENDING,
        due_date__lt=today,
    ).count()
    return {
        "type": "followup_overdue",
        "priority": PRIORITY_HIGH,
        "title": "Call overdue leads",
        "count": count,
        "cta": "/crm/followups?status=overdue",
        "description": f"{count} follow-up(s) are past their due date.",
    }


# ── Rule B ────────────────────────────────────────────────────────────────────

def _hot_leads_not_contacted(tenant, today: date) -> dict:
    from crm.models import Enquiry, EnquiryActivity
    two_days_ago = today - timedelta(days=2)

    # Exclude auto-generated CREATED/FOLLOWUP_SCHEDULED events — only
    # human interactions (calls, notes, stage changes) count as "contacted".
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
        "type": "hot_leads_not_contacted",
        "priority": PRIORITY_HIGH,
        "title": "Contact hot leads immediately",
        "count": count,
        "cta": "/crm/",
        "description": f"{count} high-priority lead(s) have not been contacted in 2+ days.",
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
        "type": "followup_due_today",
        "priority": PRIORITY_MEDIUM,
        "title": "Complete today's follow-ups",
        "count": count,
        "cta": "/crm/followups?status=due_today",
        "description": f"{count} follow-up(s) are scheduled for today.",
    }


# ── Rule D ────────────────────────────────────────────────────────────────────

def _expiring_memberships(tenant, today: date) -> dict:
    from apps.memberships.models import Membership
    in_7_days = today + timedelta(days=7)
    count = Membership.base_objects.filter(
        tenant=tenant,
        status="active",
        end_date__gte=today,
        end_date__lte=in_7_days,
        is_deleted=False,
    ).count()
    return {
        "type": "expiring_memberships",
        "priority": PRIORITY_HIGH,
        "title": "Renew expiring memberships",
        "count": count,
        "cta": "/memberships/?status=active",
        "description": f"{count} membership(s) expire within 7 days.",
    }


# ── Rule E ────────────────────────────────────────────────────────────────────

def _at_risk_members(tenant, today: date) -> dict:
    from apps.attendance.models import Attendance
    from apps.memberships.models import Membership
    seven_days_ago = today - timedelta(days=7)

    recent_attendees = (
        Attendance.base_objects.filter(
            tenant=tenant,
            status="present",
            session_date__gte=seven_days_ago,
            is_deleted=False,
        )
        .values("member_id")
        .distinct()
    )

    count = (
        Membership.base_objects.filter(
            tenant=tenant,
            status="active",
            is_deleted=False,
        )
        .exclude(member_id__in=Subquery(recent_attendees))
        .values("member_id")
        .distinct()
        .count()
    )
    return {
        "type": "at_risk_members",
        "priority": PRIORITY_HIGH,
        "title": "Re-engage at-risk members",
        "count": count,
        "cta": "/members/",
        "description": f"{count} active member(s) haven't attended in 7+ days.",
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
        "type": "low_utilization_slots",
        "priority": PRIORITY_MEDIUM,
        "title": "Promote under-booked sessions",
        "count": count,
        "cta": "/sessions/",
        "description": f"{count} session(s) in the next 7 days are below 30% capacity.",
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
        "type": "payment_pending",
        "priority": PRIORITY_HIGH,
        "title": "Collect outstanding payments",
        "count": count,
        "cta": "/memberships/?payment_status=unpaid",
        "description": f"{count} membership(s) have outstanding payments.",
    }
