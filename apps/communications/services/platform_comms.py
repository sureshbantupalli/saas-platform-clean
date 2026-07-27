"""Platform-level messaging — ANJASI speaking as itself, not as a studio.

Used for onboarding a new studio, subscription invoices, payment-failure
notices and service announcements. These are addressed to *tenant owners*,
not to studio members.

Everything routes through the existing communications engine under the
internal ANJASI tenant, so templates, trigger rules, rate limiting,
CommunicationLog and the retry command all apply unchanged. Adding a new
platform message needs no code here — add a MessageTemplate and TriggerRule
against the platform tenant, exactly as for a studio.

Recipients are ordinary context fields (``email`` / ``phone``), because
``_resolve_recipient`` reads them from the payload rather than from a Member.
That is what lets platform messages address people who are not members of
anything.
"""

import logging

from apps.core.platform import PlatformTenantMissing, get_platform_tenant

logger = logging.getLogger("apps.communications.platform")

# Platform events. Kept as constants so callers cannot drift on spelling —
# a typo'd event name matches no TriggerRule and sends nothing, silently.
TENANT_INVITED = "platform_tenant_invited"
TENANT_ACTIVATED = "platform_tenant_activated"
SUBSCRIPTION_INVOICE = "platform_subscription_invoice"
SUBSCRIPTION_PAYMENT_FAILED = "platform_subscription_payment_failed"
SERVICE_NOTICE = "platform_service_notice"


def notify_platform(event_name: str, payload: dict) -> bool:
    """Fire a platform-level event. Returns True if it was dispatched.

    Never raises. Platform messaging is always a side-effect of some more
    important operation (provisioning a tenant, recording a payment), and an
    email failure must not roll that operation back. Failures are logged at
    error level so they are visible rather than swallowed.
    """
    from apps.communications.services.communication_service import handle_event

    try:
        tenant = get_platform_tenant()
    except PlatformTenantMissing:
        logger.error(
            "[Platform] Cannot send platform message — no platform tenant. "
            "Run: manage.py ensure_platform_tenant",
            extra={"event": event_name},
        )
        return False

    # handle_event iterates matching TriggerRules and does nothing when there
    # are none. For platform mail that silence is dangerous — an unconfigured
    # invoice event would look successful while sending nothing — so the
    # no-rule case is reported as a failure rather than a quiet success.
    from apps.communications.models import TriggerRule

    if not TriggerRule.base_objects.filter(
        tenant=tenant,
        event_name=event_name,
        is_active=True,
        template__is_active=True,
    ).exists():
        logger.error(
            "[Platform] No active trigger rule for platform event — nothing sent. "
            "Add a MessageTemplate + TriggerRule against the platform tenant.",
            extra={"event": event_name},
        )
        return False

    try:
        handle_event(event_name, payload, tenant)
    except Exception:
        # handle_event already logs per-message failures to CommunicationLog;
        # this catches an unexpected failure in the dispatch itself.
        logger.exception(
            "[Platform] Failed to dispatch platform event",
            extra={"event": event_name},
        )
        return False

    return True
