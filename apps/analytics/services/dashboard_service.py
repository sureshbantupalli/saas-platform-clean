"""
Analytics Dashboard Service — read-only, multi-tenant, action-oriented.

get_dashboard_summary(tenant) → dict

All queries use base_objects (tenant-scoped apps) or objects.filter(tenant=tenant)
(root-level apps) to ensure strict isolation. Never touches another tenant's data.

Query budget: one DB round-trip per logical section, using aggregate/annotate.
Target: < 300 ms total for a typical tenant.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import (
    Avg, Count, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum, DurationField,
)
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone


# ── Lazy model imports (avoid circular imports at module load) ────────────────

def _models():
    from crm.models import Enquiry, EnquiryActivity, FollowUp
    from members.models import Member
    from apps.memberships.models import Membership
    from apps.payments.models import Payment, PaymentStatus
    from apps.attendance.models import Attendance
    return Enquiry, EnquiryActivity, FollowUp, Member, Membership, Payment, PaymentStatus, Attendance


# ── Public entry point ────────────────────────────────────────────────────────

def get_dashboard_summary(tenant) -> dict:
    Enquiry, EnquiryActivity, FollowUp, Member, Membership, Payment, PaymentStatus, Attendance = _models()

    today            = date.today()
    now              = timezone.now()
    thirty_days_ago  = now - timedelta(days=30)
    seven_days_ago   = (now - timedelta(days=7)).date()
    fourteen_days_ago = (now - timedelta(days=14)).date()
    month_start      = today.replace(day=1)

    summary   = _summary(tenant, today, thirty_days_ago, month_start,
                         Member, Membership, Payment, PaymentStatus, Enquiry)
    alerts    = _alerts(tenant, today, seven_days_ago,
                        FollowUp, Membership, Attendance, Enquiry, EnquiryActivity)
    charts    = _charts(tenant, thirty_days_ago, Payment, PaymentStatus, Enquiry, Attendance)
    attendance = _attendance_metrics(tenant, thirty_days_ago, Attendance)
    retention  = _retention(tenant, thirty_days_ago, Membership)
    peak_hours = _peak_hours(tenant, thirty_days_ago, Attendance)
    at_risk    = _at_risk_count(tenant, seven_days_ago, Membership, Attendance)
    engagement = _engagement(tenant, fourteen_days_ago, summary["active_members"], Attendance)

    return {
        "summary":          summary,
        "alerts":           alerts,
        "charts":           charts,
        "attendance":       attendance,
        "retention":        retention,
        "peak_hours":       peak_hours,
        "at_risk_members":  {"count": at_risk},
        "engagement":       engagement,
    }


# ── Section helpers ───────────────────────────────────────────────────────────

def _summary(tenant, today, thirty_days_ago, month_start,
             Member, Membership, Payment, PaymentStatus, Enquiry) -> dict:
    total_members = Member.objects.filter(tenant=tenant, is_deleted=False).count()

    active_members = (
        Membership.base_objects
        .filter(tenant=tenant, status="active", is_deleted=False)
        .values("member_id").distinct().count()
    )

    new_members_30d = Member.objects.filter(
        tenant=tenant, is_deleted=False, created_at__gte=thirty_days_ago,
    ).count()

    lead_agg = Enquiry.objects.filter(tenant=tenant).aggregate(
        total=Count("id"),
        converted=Count("id", filter=Q(converted_member__isnull=False)),
    )
    total_leads     = lead_agg["total"] or 0
    converted_leads = lead_agg["converted"] or 0
    conversion_rate = round(converted_leads / total_leads * 100, 1) if total_leads else 0.0

    rev = Payment.base_objects.filter(
        tenant=tenant,
        status=PaymentStatus.SUCCESS,
        created_at__date__gte=month_start,
        is_deleted=False,
    ).aggregate(total=Sum("amount"))
    revenue_mtd = rev["total"] or Decimal("0")

    pending = Payment.base_objects.filter(
        tenant=tenant,
        status__in=[PaymentStatus.PENDING, PaymentStatus.CREATED],
        is_deleted=False,
    ).aggregate(count=Count("id"), total=Sum("amount"))

    return {
        "total_members":           total_members,
        "active_members":          active_members,
        "new_members_last_30_days": new_members_30d,
        "total_leads":             total_leads,
        "converted_leads":         converted_leads,
        "conversion_rate":         conversion_rate,
        "revenue_mtd":             str(revenue_mtd),
        "pending_payments_count":  pending["count"] or 0,
        "pending_payments_amount": str(pending["total"] or Decimal("0")),
    }


def _alerts(tenant, today, seven_days_ago,
            FollowUp, Membership, Attendance, Enquiry, EnquiryActivity) -> list:
    alerts = []

    # ── Follow-ups due today ──────────────────────────────────────────────────
    due_today = FollowUp.objects.filter(
        tenant=tenant, status=FollowUp.STATUS_PENDING, due_date=today,
    ).count()
    if due_today:
        alerts.append({
            "type":    "followup_due_today",
            "count":   due_today,
            "message": f"{due_today} follow-up{'s' if due_today != 1 else ''} due today",
            "level":   "warning",
        })

    # ── Overdue follow-ups ───────────────────────────────────────────────────
    overdue = FollowUp.objects.filter(
        tenant=tenant, status=FollowUp.STATUS_PENDING, due_date__lt=today,
    ).count()
    if overdue:
        alerts.append({
            "type":    "followup_overdue",
            "count":   overdue,
            "message": f"{overdue} overdue follow-up{'s' if overdue != 1 else ''} need attention",
            "level":   "danger",
        })

    # ── Memberships expiring in 7 days ───────────────────────────────────────
    expiring = Membership.base_objects.filter(
        tenant=tenant,
        status="active",
        is_deleted=False,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=7),
    ).count()
    if expiring:
        alerts.append({
            "type":    "membership_expiring",
            "count":   expiring,
            "message": f"{expiring} membership{'s' if expiring != 1 else ''} expiring in 7 days",
            "level":   "warning",
        })

    # ── At-risk members (active membership, no attendance last 7 days) ───────
    at_risk = _at_risk_count(tenant, seven_days_ago, Membership, Attendance)
    if at_risk:
        alerts.append({
            "type":    "at_risk_members",
            "count":   at_risk,
            "message": f"{at_risk} active member{'s' if at_risk != 1 else ''} haven't attended in 7 days",
            "level":   "warning",
        })

    # ── Hot leads not contacted in last 3 days ───────────────────────────────
    recent_contact_ids = (
        EnquiryActivity.objects
        .filter(
            tenant=tenant,
            created_at__gte=timezone.now() - timedelta(days=3),
            action_type__in=["CALL_LOGGED", "FOLLOWUP_DONE", "STAGE_CHANGED"],
        )
        .values_list("enquiry_id", flat=True)
    )
    hot_leads = (
        Enquiry.objects
        .filter(
            tenant=tenant,
            next_followup_date__lte=today,
            converted_member__isnull=True,
        )
        .filter(Q(current_stage__isnull=True) | Q(current_stage__is_loss_stage=False))
        .exclude(id__in=recent_contact_ids)
        .count()
    )
    if hot_leads:
        alerts.append({
            "type":    "hot_leads_not_contacted",
            "count":   hot_leads,
            "message": f"{hot_leads} hot lead{'s' if hot_leads != 1 else ''} haven't been contacted recently",
            "level":   "info",
        })

    return alerts


def _charts(tenant, thirty_days_ago, Payment, PaymentStatus, Enquiry, Attendance) -> dict:
    # Revenue trend — daily SUCCESS payments for last 30 days
    revenue_rows = (
        Payment.base_objects
        .filter(
            tenant=tenant, status=PaymentStatus.SUCCESS,
            created_at__gte=thirty_days_ago, is_deleted=False,
        )
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(amount=Sum("amount"))
        .order_by("day")
    )
    revenue_trend = [
        {"date": str(r["day"]), "amount": str(r["amount"])}
        for r in revenue_rows
    ]

    # Lead conversion funnel
    funnel = Enquiry.objects.filter(tenant=tenant).aggregate(
        total=Count("id"),
        converted=Count("id", filter=Q(converted_member__isnull=False)),
        lost=Count("id", filter=Q(current_stage__is_loss_stage=True)),
    )
    total     = funnel["total"] or 0
    converted = funnel["converted"] or 0
    lost      = funnel["lost"] or 0
    lead_funnel = {
        "total":     total,
        "converted": converted,
        "lost":      lost,
        "active":    max(total - converted - lost, 0),
    }

    # Attendance trend — daily present count for last 30 days
    attendance_rows = (
        Attendance.base_objects
        .filter(
            tenant=tenant, status="present",
            session_date__gte=thirty_days_ago.date(),
            is_deleted=False,
        )
        .values("session_date")
        .annotate(count=Count("id"))
        .order_by("session_date")
    )
    attendance_trend = [
        {"date": str(r["session_date"]), "count": r["count"]}
        for r in attendance_rows
    ]

    return {
        "revenue_trend":    revenue_trend,
        "lead_funnel":      lead_funnel,
        "attendance_trend": attendance_trend,
    }


def _attendance_metrics(tenant, thirty_days_ago, Attendance) -> dict:
    qs = Attendance.base_objects.filter(
        tenant=tenant, status="present",
        session_date__gte=thirty_days_ago.date(),
        is_deleted=False,
    )
    total_attendance   = qs.count()
    total_sessions     = qs.values("session_date").distinct().count()
    avg_per_session    = round(total_attendance / total_sessions, 1) if total_sessions else 0.0

    return {
        "total_last_30_days":         total_attendance,
        "total_sessions_last_30_days": total_sessions,
        "avg_per_session":            avg_per_session,
    }


def _retention(tenant, thirty_days_ago, Membership) -> dict:
    active = (
        Membership.base_objects
        .filter(tenant=tenant, status="active", is_deleted=False)
        .values("member_id").distinct().count()
    )

    churned = (
        Membership.base_objects
        .filter(
            tenant=tenant,
            status__in=["expired", "cancelled"],
            is_deleted=False,
            updated_at__gte=thirty_days_ago,
        )
        .values("member_id").distinct().count()
    )

    denominator    = active + churned
    retention_rate = round(active / denominator * 100, 1) if denominator else 100.0

    avg_dur = (
        Membership.base_objects
        .filter(tenant=tenant, is_deleted=False)
        .annotate(
            duration=ExpressionWrapper(
                F("end_date") - F("start_date"), output_field=DurationField()
            )
        )
        .aggregate(avg=Avg("duration"))
    )
    avg_days = avg_dur["avg"].days if avg_dur["avg"] else 0

    return {
        "active_members":          active,
        "churned_last_30_days":    churned,
        "retention_rate":          retention_rate,
        "avg_membership_duration_days": avg_days,
    }


def _peak_hours(tenant, thirty_days_ago, Attendance) -> list:
    """Return hourly attendance counts for last 30 days (check_in_time only)."""
    rows = (
        Attendance.base_objects
        .filter(
            tenant=tenant,
            status="present",
            session_date__gte=thirty_days_ago.date(),
            check_in_time__isnull=False,
            is_deleted=False,
        )
        .annotate(hour=ExtractHour("check_in_time"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )
    return [{"hour": r["hour"], "count": r["count"]} for r in rows]


def _at_risk_count(tenant, seven_days_ago, Membership, Attendance) -> int:
    """Members with an active membership but no attendance in the last 7 days."""
    recent_attendees = (
        Attendance.base_objects
        .filter(
            tenant=tenant, status="present",
            session_date__gte=seven_days_ago,
            is_deleted=False,
        )
        .values("member_id")
    )
    return (
        Membership.base_objects
        .filter(tenant=tenant, status="active", is_deleted=False)
        .exclude(member_id__in=Subquery(recent_attendees))
        .values("member_id")
        .distinct()
        .count()
    )


def _engagement(tenant, fourteen_days_ago, active_members, Attendance) -> dict:
    """Members who attended at least once in the last 14 days."""
    engaged = (
        Attendance.base_objects
        .filter(
            tenant=tenant, status="present",
            session_date__gte=fourteen_days_ago,
            is_deleted=False,
        )
        .values("member_id")
        .distinct()
        .count()
    )
    rate = round(engaged / active_members * 100, 1) if active_members else 0.0
    return {
        "engaged_last_14_days": engaged,
        "engagement_rate":      rate,
    }
