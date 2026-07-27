"""
Phase 7.2 — Explainability layer.

Read-only. Composes from audit logs + revenue signal + payment state.
Every explanation is traceable to an actual system record — no inference,
no guessing, no side effects.
"""
from apps.audit.models import AuditModule
from apps.audit.timeline_service import get_timeline

# Single source of truth for which audit module covers nudge/communication events.
# When email/SMS/push channels are added, update this constant — not a search-replace.
NUDGE_MODULE = AuditModule.WHATSAPP


# ── Internal helpers ──────────────────────────────────────────────────────────

def _summarize_log(log):
    return {
        "when":   log.timestamp,
        "what":   f"{log.module}.{log.action}",
        "field":  log.field_name,
        "from":   str(log.old_value)[:100] if log.old_value is not None else None,
        "to":     str(log.new_value)[:100] if log.new_value is not None else None,
        "source": log.source,
    }


_RISK_REASON_LABELS = {
    "missed_2_payments":       "Member has missed two consecutive payments.",
    "missed_1_no_engagement":  "Member missed a payment and has not engaged recently.",
    "missed_1":                "Member has missed one payment.",
}

_RISK_SUMMARIES = {
    "high":    "Member is high risk.",
    "medium":  "Member shows early risk signals.",
    "low":     "No immediate risk detected.",
    "unknown": "Risk level not yet computed.",
}


# IMPORTANT:
# build_summary() MUST NOT derive or recompute business logic.
# It only maps existing fields (risk_level, risk_reason) to human-readable text.
# Do not add conditionals that re-evaluate payment counts, dates, or thresholds —
# that logic belongs in revenue_signal_service.py, not here.
def build_summary(explanation):
    risk_level  = explanation.get("risk_level")
    risk_reason = explanation.get("risk_reason")

    reason_label = _RISK_REASON_LABELS.get(risk_reason, "")
    level_label  = _RISK_SUMMARIES.get(risk_level, "No risk data available.")

    if reason_label:
        return f"{level_label} {reason_label}".strip()
    return level_label


# ── Public API ────────────────────────────────────────────────────────────────

def explain_member(member, *, tenant):
    """
    Returns risk signal + recent audit activity for a member.
    Costs exactly 2 DB queries: one for logs, one for signal.
    """
    from apps.revenue.models import MemberRevenueSignal

    logs   = get_timeline(tenant=tenant, member_id=str(member.id), limit=20)
    signal = MemberRevenueSignal.objects.filter(member=member).first()

    explanation = {
        "member_id":       str(member.id),
        "risk_level":      getattr(signal, "risk_level",  "unknown"),
        "risk_reason":     getattr(signal, "risk_reason", None),
        "recent_activity": [_summarize_log(log) for log in logs],
    }
    explanation["summary"] = build_summary(explanation)
    return explanation


def explain_payment(payment, *, tenant):
    """
    Returns committed payment status + recent audit activity for a payment.
    Costs exactly 1 DB query: one for logs.
    """
    logs = get_timeline(tenant=tenant, payment_id=str(payment.id), limit=20)

    return {
        "payment_id":      str(payment.id),
        "status":          payment.status,
        "recent_activity": [_summarize_log(log) for log in logs],
    }


def explain_nudge(member, *, tenant):
    """
    Returns nudge audit events for a member.
    Costs exactly 1 DB query.
    """
    logs = get_timeline(
        tenant=tenant,
        member_id=str(member.id),
        module=NUDGE_MODULE,
        limit=20,
    )

    return {
        "member_id":    str(member.id),
        "nudge_events": [_summarize_log(log) for log in logs],
    }
