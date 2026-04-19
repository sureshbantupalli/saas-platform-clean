"""
Standard event contract for the Communications module.

All modules emitting communication events must use CommunicationEvent to
guarantee a consistent wire format. The Communications module depends
ONLY on this contract — never on the emitting module's internal models.

Wire format (what handle_event() receives as payload):
    {
        "event":       "payment_success",
        "tenant_id":   "<uuid>",
        "entity_type": "member",
        "entity_id":   "<uuid>",
        "data": {
            "member_name": "...",
            "phone":       "...",
            ...
        }
    }

The "data" dict is used as the template rendering context.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CommunicationEvent:
    """Typed wrapper for outbound communication events."""
    event:       str
    tenant_id:   str
    entity_type: str
    entity_id:   str
    data:        dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        """Return the standard dict consumed by handle_event()."""
        return {
            "event":       self.event,
            "tenant_id":   self.tenant_id,
            "entity_type": self.entity_type,
            "entity_id":   self.entity_id,
            "data":        self.data,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> CommunicationEvent:
        return cls(
            event       = payload.get("event", ""),
            tenant_id   = payload.get("tenant_id", ""),
            entity_type = payload.get("entity_type", ""),
            entity_id   = payload.get("entity_id", ""),
            data        = payload.get("data") if isinstance(payload.get("data"), dict) else {},
        )


def extract_context(payload: dict) -> dict:
    """
    Normalize a payload to the flat dict used as template context.

    Supports both formats:
    - Standard: {"event": ..., "data": {"member_name": ...}}  → returns data dict
    - Legacy flat: {"member_name": ..., "phone": ...}         → returns payload as-is

    This lets existing callers (and tests) pass flat dicts without changes.
    """
    if isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


# ── Event Registry ─────────────────────────────────────────────────────────────
#
# Maps event_name → expected template variables + metadata.
# Used to validate payloads at send time and to document the contract.
# New events can be registered here without touching any other code.

@dataclass
class EventDefinition:
    description:     str
    expected_fields: list
    entity_type:     str = ""


EVENT_REGISTRY: dict[str, EventDefinition] = {
    "payment_success": EventDefinition(
        description     = "Fired when a payment succeeds.",
        expected_fields = ["member_name", "phone", "amount"],
        entity_type     = "member",
    ),
    "payment_failed": EventDefinition(
        description     = "Fired when a payment fails.",
        expected_fields = ["member_name", "phone", "amount"],
        entity_type     = "member",
    ),
    "membership_activated": EventDefinition(
        description     = "Fired when a membership transitions to active.",
        expected_fields = ["member_name", "phone", "plan_name"],
        entity_type     = "member",
    ),
    "membership_expiring": EventDefinition(
        description     = "Fired when a membership is close to expiry.",
        expected_fields = ["member_name", "phone", "plan_name", "expiry_date", "days_remaining"],
        entity_type     = "member",
    ),
    "followup_due": EventDefinition(
        description     = "Fired for CRM follow-ups due today or overdue.",
        expected_fields = ["name", "phone", "due_date"],
        entity_type     = "contact",
    ),
    "booking_confirmed": EventDefinition(
        description     = "Fired when a session booking is confirmed.",
        expected_fields = ["member_name", "phone", "session_type", "session_date"],
        entity_type     = "member",
    ),
    "session_reminder": EventDefinition(
        description     = "Fired as a reminder before a session.",
        expected_fields = ["member_name", "phone", "session_type", "session_time"],
        entity_type     = "member",
    ),
    "attendance_marked": EventDefinition(
        description     = "Fired when attendance is recorded.",
        expected_fields = ["member_name", "phone", "session_date"],
        entity_type     = "member",
    ),
}


def validate_event_payload(event_name: str, context: dict) -> list:
    """
    Return list of expected fields absent from context.
    Empty list = all required fields present (or event is unregistered).
    Does NOT raise — callers log the result and continue.
    """
    defn = EVENT_REGISTRY.get(event_name)
    if defn is None:
        return []
    return [f for f in defn.expected_fields if not context.get(f)]


def get_event_definition(event_name: str) -> EventDefinition | None:
    return EVENT_REGISTRY.get(event_name)
