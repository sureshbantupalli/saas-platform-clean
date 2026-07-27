"""
Audit service layer.

Public API (use these in all integration call sites):
    safe_log_change(**kwargs)       — fault-tolerant; never raises; logs exceptions
    log_payment_change(...)         — convenience wrapper for payments module
    log_membership_change(...)      — convenience wrapper for memberships module

Internal:
    log_change(**kwargs)            — raw implementation; CAN raise; do not call directly
    _serialize(value)               — serialize any Python value for TextField storage
    normalize(value)                — stable string for equality comparison (diff detection)
    _json_default(obj)              — JSON encoder for datetime/date → isoformat

Design rules:
    - ALL integration call sites must use safe_log_change (never log_change directly)
    - Log ONLY after a state change has been confirmed (not speculatively)
    - For payment flows: always call via transaction.on_commit so the log
      reflects only committed state
    - source='user' for human actions, source='system' for automated flows

INVARIANT — timeline is reflective, never authoritative:
    The audit log stores REFERENCES (payment_id, member_id) — not financial values.
    Reports are computed from Payment/Expense/Payout models, never from audit logs.
    Corollary: deleting all SettingsAuditLog rows must leave every financial report unchanged.
    Violations are caught at write time by log_change (see _FINANCIAL_FIELD_GUARD below).
"""
import json
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


# Fields and metadata keys whose presence in an audit log entry indicates a
# design error: the caller is storing a financial value rather than a reference.
# Adding an amount here means you can reconstruct money from the timeline — which
# breaks the invariant that reports are computed solely from source models.
_FINANCIAL_FIELD_GUARD = frozenset({
    'amount', 'gst_amount', 'gst_rate', 'total', 'net_profit',
    'taxable_income', 'net_gst_liability', 'refund_amount',
})
_FINANCIAL_METADATA_KEYS = frozenset({
    'amount', 'gst_amount', 'gst_rate', 'refund_amount',
})


# ── Serialization helpers ─────────────────────────────────────────────────────

def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def _serialize(value) -> 'str | None':
    """
    Serialize a value for storage in old_value / new_value.

    - None    → None      (preserved as NULL in the DB)
    - str     → as-is     (already a stable representation)
    - other   → json.dumps(default=_json_default) — queryable, analytics-ready
    - fallback → str()    — never raises, always stores something
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=_json_default)
    except Exception:
        return str(value)


def normalize(value) -> str:
    """
    Stable string representation for equality comparison (diff detection).

    Use this to decide WHETHER to log — never use it for storage.
    dict/list → json.dumps(sort_keys=True) so key order is irrelevant.
    everything else → str().
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


# ── Core write ────────────────────────────────────────────────────────────────

def log_change(
    *,
    tenant,
    user=None,
    module: str,
    action: str,
    source: str = 'system',
    field_name: 'str | None' = None,
    old_value=None,
    new_value=None,
    metadata: 'dict | None' = None,
) -> None:
    """
    Raw audit write — can raise.  Do NOT call this from integration code.
    All callers must go through safe_log_change.

    Enforces the timeline invariant: financial values must not be stored here.
    Store a reference (payment_id, expense_id) and fetch the value from the
    source model when needed.
    """
    if field_name in _FINANCIAL_FIELD_GUARD:
        raise ValueError(
            f"audit.log_change: field_name='{field_name}' is a financial field. "
            "Store only a reference (e.g. payment_id) and read the value from "
            "the source model. The audit log must not be a source of financial truth."
        )
    if metadata:
        bad_keys = _FINANCIAL_METADATA_KEYS & set(metadata)
        if bad_keys:
            raise ValueError(
                f"audit.log_change: metadata contains financial keys {sorted(bad_keys)!r}. "
                "Store only a reference (e.g. payment_id) and read the value from "
                "the source model. The audit log must not be a source of financial truth."
            )

    from apps.audit.models import SettingsAuditLog

    SettingsAuditLog.objects.create(
        tenant=tenant,
        user=user,
        module=module,
        action=action,
        source=source,
        field_name=field_name,
        old_value=_serialize(old_value),
        new_value=_serialize(new_value),
        metadata=metadata if metadata is not None else {},
    )


# ── Public API (fault-tolerant) ───────────────────────────────────────────────

def safe_log_change(**kwargs) -> None:
    """
    Fault-tolerant wrapper around log_change.

    RULE: ALL integration call sites must use this — never call log_change directly.
    Guarantees:
      - logging never raises into the calling code
      - exception is logged so ops can observe audit failures without crashing flows
    """
    try:
        log_change(**kwargs)
    except Exception:
        logger.exception('safe_log_change: audit write failed silently')


# ── Domain helpers (module-pinned wrappers) ───────────────────────────────────

def log_payment_change(
    *, tenant, user=None, action, field_name=None,
    old_value=None, new_value=None, metadata=None,
) -> None:
    from apps.audit.models import AuditModule
    safe_log_change(
        tenant=tenant, user=user, module=AuditModule.PAYMENTS, action=action,
        source='system',
        field_name=field_name, old_value=old_value, new_value=new_value, metadata=metadata,
    )


def log_membership_change(
    *, tenant, user=None, action, field_name=None,
    old_value=None, new_value=None, metadata=None,
) -> None:
    from apps.audit.models import AuditModule
    safe_log_change(
        tenant=tenant, user=user, module=AuditModule.MEMBERSHIPS, action=action,
        source='user' if user else 'system',
        field_name=field_name, old_value=old_value, new_value=new_value, metadata=metadata,
    )


def log_booking_change(
    *, tenant, user=None, action, source=None, field_name=None,
    old_value=None, new_value=None, metadata=None,
) -> None:
    from apps.audit.models import AuditModule
    safe_log_change(
        tenant=tenant, user=user, module=AuditModule.BOOKINGS, action=action,
        source=source or ('user' if user else 'system'),
        field_name=field_name, old_value=old_value, new_value=new_value, metadata=metadata,
    )


def log_attendance_change(
    *, tenant, user=None, action, source=None, field_name=None,
    old_value=None, new_value=None, metadata=None,
) -> None:
    from apps.audit.models import AuditModule
    safe_log_change(
        tenant=tenant, user=user, module=AuditModule.ATTENDANCE, action=action,
        source=source or ('user' if user else 'system'),
        field_name=field_name, old_value=old_value, new_value=new_value, metadata=metadata,
    )
