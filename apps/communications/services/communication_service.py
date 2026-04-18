"""
Communication service — core entry points.

handle_event(event_name, payload, tenant)
    Main entry point. Finds active TriggerRules, evaluates conditions,
    renders templates, sends messages, and logs results.

send_message(template, context, tenant, ...)
    Resolves recipient, picks adapter, sends, and writes CommunicationLog.
"""
import logging

from apps.communications.models import (
    Channel, CommunicationLog, MessageStatus, MessageTemplate, TriggerRule,
)
from apps.communications.utils.conditions import evaluate_conditions
from apps.communications.utils.renderer import render_template

logger = logging.getLogger("apps.communications")

# Field names to try when resolving recipient per channel
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


def _resolve_recipient(channel: str, payload: dict) -> str:
    for field in _RECIPIENT_FIELDS.get(channel, []):
        value = payload.get(field, "")
        if value:
            return str(value)
    return ""


def send_message(
    template: MessageTemplate,
    context: dict,
    tenant,
    reference_type: str = "",
    reference_id: str = "",
) -> CommunicationLog:
    """
    Render the template with context, pick the right adapter, send, and log.
    Always returns a CommunicationLog — never raises.
    """
    channel   = template.channel
    recipient = _resolve_recipient(channel, context)
    message   = render_template(template.content, context)
    subject   = render_template(template.subject, context) if template.subject else ""

    log = CommunicationLog(
        tenant         = tenant,
        channel        = channel,
        recipient      = recipient or "unknown",
        subject        = subject,
        message        = message,
        status         = MessageStatus.PENDING,
        reference_type = reference_type,
        reference_id   = str(reference_id) if reference_id else "",
    )

    if not recipient:
        log.status        = MessageStatus.FAILED
        log.error_message = "No recipient found in payload."
        log.save()
        logger.warning(
            "[Communications] No recipient for channel=%s template=%s", channel, template.name
        )
        return log

    adapter = _get_adapter(channel)
    if adapter is None:
        log.status        = MessageStatus.FAILED
        log.error_message = f"No adapter registered for channel: {channel}"
        log.save()
        return log

    try:
        adapter.send(to=recipient, message=message, subject=subject)
        log.status = MessageStatus.SENT
    except Exception as exc:
        log.status        = MessageStatus.FAILED
        log.error_message = str(exc)
        logger.exception("[Communications] Send failed for channel=%s: %s", channel, exc)

    log.save()
    return log


def handle_event(event_name: str, payload: dict, tenant) -> None:
    """
    Entry point for all system events.

    Looks up active TriggerRules for this tenant + event, evaluates optional
    conditions against the payload, then sends a message for each matching rule.

    New events can be wired in without any code change — just add a TriggerRule.
    """
    rules = (
        TriggerRule.base_objects
        .filter(tenant=tenant, event_name=event_name, is_active=True, template__is_active=True)
        .select_related("template")
    )

    for rule in rules:
        try:
            if not evaluate_conditions(rule.conditions, payload):
                logger.debug(
                    "[Communications] Conditions not met for rule=%s event=%s", rule.pk, event_name
                )
                continue

            send_message(
                template       = rule.template,
                context        = payload,
                tenant         = tenant,
                reference_type = payload.get("reference_type", ""),
                reference_id   = payload.get("reference_id", ""),
            )
        except Exception as exc:
            logger.exception(
                "[Communications] Unhandled error in rule=%s event=%s: %s", rule.pk, event_name, exc
            )
