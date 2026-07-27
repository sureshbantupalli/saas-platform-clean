"""
Communication service — core entry points.

handle_event(event_name, payload, tenant)
    Main entry point called by all signal receivers.
    Normalizes payload, validates fields, checks rate limit,
    resolves matching TriggerRules, and delegates to send_message().

send_message(template, context, tenant, ...)
    Resolves recipient, applies rate limit, picks adapter, sends, logs.
    Always returns a CommunicationLog — never raises.

Payload normalization (backward compatible):
    Standard format: {"event": ..., "data": {"member_name": ...}}
        → template context = payload["data"]
    Legacy flat format: {"member_name": ..., "phone": ...}
        → template context = payload  (unchanged)
"""
import logging

from django.utils import timezone

from datetime import timedelta

from apps.communications.models import (
    Channel, CommunicationLog, MessageStatus, MessageTemplate, Priority, TriggerRule,
)
from apps.communications.services.event_schema import (
    extract_context, make_dedupe_key, validate_event_payload,
)
from apps.communications.utils.conditions import evaluate_conditions
from apps.communications.utils.renderer import render_template, extract_placeholders

logger = logging.getLogger("apps.communications")


def _record_attempt(
    tenant,
    event_type: str,
    channel: str,
    status: str,
    log=None,
    error_code: str = '',
    error_message: str = '',
) -> None:
    try:
        from apps.engagement.models import MessageAttempt
        MessageAttempt.objects.create(
            tenant=tenant,
            event_name=event_type,
            channel=channel,
            status=status,
            communication_log=log,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception:
        pass  # never break message delivery for tracking failures

# Ordered preference when resolving recipient address per channel
_RECIPIENT_FIELDS = {
    Channel.SMS:      ["phone", "mobile", "phone_number"],
    Channel.WHATSAPP: ["whatsapp", "phone", "mobile", "phone_number"],
    Channel.EMAIL:    ["email"],
}


def _get_adapter(channel: str):
    from apps.communications.adapters.sms import SMSAdapter
    from apps.communications.adapters.whatsapp import WhatsAppAdapter
    from apps.communications.adapters.email import EmailAdapter

    return {
        Channel.SMS:      SMSAdapter(),
        Channel.WHATSAPP: WhatsAppAdapter(),
        Channel.EMAIL:    EmailAdapter(),
    }.get(channel)


def _resolve_recipient(channel: str, context: dict) -> str:
    for field in _RECIPIENT_FIELDS.get(channel, []):
        value = context.get(field, "")
        if value:
            return str(value)
    return ""


def send_message(
    template: MessageTemplate,
    context: dict,
    tenant,
    reference_type: str = "",
    reference_id: str = "",
    event_type: str = "",
    dedupe_key: str = "",
) -> CommunicationLog:
    """
    Render the template with context, apply rate limit, pick the right adapter,
    send, and write a CommunicationLog. Always returns a log — never raises.
    """
    from django.conf import settings

    channel   = template.channel
    recipient = _resolve_recipient(channel, context)
    text_message = ""

    if channel == Channel.EMAIL:
        from apps.branding_adapter.email_renderer import (
            render_branded_email, render_branded_email_text,
        )
        from apps.branding_adapter.branding_adapter import BrandingAdapter

        branding_ctx = BrandingAdapter.get_branding_context(tenant)
        message      = render_branded_email(template.content, context, tenant)
        text_message = render_branded_email_text(template.content, context, tenant)
    elif channel == Channel.WHATSAPP:
        from apps.branding_adapter.whatsapp_adapter import WhatsAppBrandingAdapter
        branding_ctx = {}
        message      = WhatsAppBrandingAdapter.format_message(
            event=event_type,
            content=template.content,
            context=context,
            tenant=tenant,
        )
    else:
        branding_ctx = {}
        message      = render_template(template.content, context)

    subject = render_template(template.subject, context) if template.subject else ""

    # Optional: prefix subject with brand name — set COMMS_BRAND_EMAIL_SUBJECT=True to enable
    if (channel == Channel.EMAIL
            and subject
            and getattr(settings, 'COMMS_BRAND_EMAIL_SUBJECT', False)):
        brand_name = branding_ctx.get('brand_name', '')
        if brand_name:
            subject = f'[{brand_name}] {subject}'

    # Warn on missing template placeholders so operators can fix templates
    missing = extract_placeholders(template.content) - set(context.keys())
    if missing:
        logger.warning(
            "[Communications] Template has unresolved placeholders",
            extra={
                "reason":      "missing_template_vars",
                "template":    template.name,
                "event":       event_type,
                "tenant_id":   str(tenant.pk) if tenant else "",
                "missing":     sorted(missing),
            },
        )

    log = CommunicationLog(
        tenant          = tenant,
        channel         = channel,
        event_type      = event_type,
        recipient       = recipient or "unknown",
        subject         = subject,
        message         = message,
        status          = MessageStatus.PENDING,
        reference_type  = reference_type,
        reference_id    = str(reference_id) if reference_id else "",
        last_attempt_at = timezone.now(),
        next_attempt_at = timezone.now(),
        priority        = getattr(template, "priority", Priority.MEDIUM),
        dedupe_key      = dedupe_key,
    )

    # ── Deduplication ─────────────────────────────────────────────────────────
    if dedupe_key:
        window = timezone.now() - timedelta(hours=24)
        duplicate = (
            CommunicationLog.base_objects
            .filter(
                tenant=tenant,
                dedupe_key=dedupe_key,
                status=MessageStatus.SENT,
                created_at__gte=window,
            )
            .exists()
        )
        if duplicate:
            log.status        = MessageStatus.SKIPPED
            log.error_message = "duplicate: already sent within 24 h"
            log.save()
            logger.info(
                "[Communications] Duplicate message suppressed",
                extra={
                    "reason":     "duplicate",
                    "dedupe_key": dedupe_key,
                    "event":      event_type,
                    "tenant_id":  str(tenant.pk) if tenant else "",
                    "channel":    channel,
                },
            )
            return log

    # ── No recipient ───────────────────────────────────────────────────────────
    if not recipient:
        log.status        = MessageStatus.FAILED
        log.error_message = "No recipient found in payload."
        log.save()
        logger.warning(
            "[Communications] No recipient — message not sent",
            extra={
                "reason":    "no_recipient",
                "channel":   channel,
                "template":  template.name,
                "event":     event_type,
                "tenant_id": str(tenant.pk) if tenant else "",
            },
        )
        return log

    # ── Rate limit ─────────────────────────────────────────────────────────────
    from apps.communications.services.rate_limiter import is_rate_limited, record_rate_limited
    if is_rate_limited(tenant):
        record_rate_limited(tenant, channel, event_type, recipient)
        log.status        = MessageStatus.FAILED
        log.error_message = "rate_limited: per-minute quota exceeded"
        # rate_limiter already wrote its own log; don't double-write
        return log

    # ── No adapter ─────────────────────────────────────────────────────────────
    adapter = _get_adapter(channel)
    if adapter is None:
        log.status        = MessageStatus.FAILED
        log.error_message = f"No adapter registered for channel: {channel}"
        log.save()
        logger.error(
            "[Communications] No adapter for channel",
            extra={
                "reason":    "no_adapter",
                "channel":   channel,
                "event":     event_type,
                "tenant_id": str(tenant.pk) if tenant else "",
            },
        )
        return log

    # ── Send ───────────────────────────────────────────────────────────────────
    _attempt_status   = 'sent'
    _attempt_errcode  = ''
    _attempt_errmsg   = ''
    try:
        adapter.send(to=recipient, message=message, subject=subject, text=text_message)
        log.status = MessageStatus.SENT
    except Exception as exc:
        log.status        = MessageStatus.FAILED
        log.error_message = str(exc)
        _attempt_status  = 'failed'
        _attempt_errcode = type(exc).__name__
        _attempt_errmsg  = str(exc)
        logger.warning(
            "[Communications] Adapter send failed",
            extra={
                "reason":    "send_failed",
                "channel":   channel,
                "event":     event_type,
                "tenant_id": str(tenant.pk) if tenant else "",
                "recipient": recipient,
                "error":     str(exc),
            },
        )

    log.save()
    _record_attempt(
        tenant, event_type, channel, _attempt_status, log,
        error_code=_attempt_errcode, error_message=_attempt_errmsg,
    )
    return log


def handle_event(event_name: str, payload: dict, tenant) -> None:
    """
    Entry point for all system events.

    1. Normalizes payload (standard or legacy flat format).
    2. Validates required fields against EventRegistry (warns, does not block).
    3. Finds active TriggerRules for this tenant + event.
    4. Evaluates optional conditions.
    5. Sends a message for each matching rule via send_message().

    New events are wired in without any code change — just add a TriggerRule.
    """
    context    = extract_context(payload)
    entity_id  = payload.get("entity_id", "")
    tenant_pk  = str(tenant.pk) if tenant else ""
    dedupe_key = make_dedupe_key(tenant_pk, event_name, entity_id) if entity_id else ""

    # Validate expected fields — log missing ones, never raise
    missing_fields = validate_event_payload(event_name, context)
    if missing_fields:
        logger.warning(
            "[Communications] Event payload missing expected fields",
            extra={
                "reason":         "missing_event_fields",
                "event":          event_name,
                "tenant_id":      str(tenant.pk) if tenant else "",
                "missing_fields": missing_fields,
            },
        )

    rules = (
        TriggerRule.base_objects
        .filter(tenant=tenant, event_name=event_name, is_active=True, template__is_active=True)
        .select_related("template")
    )

    for rule in rules:
        try:
            if not evaluate_conditions(rule.conditions, context):
                logger.debug(
                    "[Communications] Conditions not met for rule=%s event=%s", rule.pk, event_name
                )
                continue

            send_message(
                template       = rule.template,
                context        = context,
                tenant         = tenant,
                reference_type = context.get("reference_type", payload.get("reference_type", "")),
                reference_id   = context.get("reference_id", payload.get("reference_id", "")),
                event_type     = event_name,
                dedupe_key     = dedupe_key,
            )
        except Exception as exc:
            logger.exception(
                "[Communications] Unhandled error in rule=%s event=%s: %s", rule.pk, event_name, exc
            )
