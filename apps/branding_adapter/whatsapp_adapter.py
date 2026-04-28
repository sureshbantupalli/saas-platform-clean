"""
WhatsAppBrandingAdapter — formats plain-text WhatsApp messages for a tenant.

Pipeline (in order):
  1. Template resolution  — per-event override > MessageTemplate.content
  2. Variable substitution — {{key}} placeholders; missing keys → ""; warns on missing
  3. Tone greeting         — FORMAL / FRIENDLY / MINIMAL (extensible via GREETING_REGISTRY)
  4. Body
  5. Signature             — appended when enabled; idempotent (won't double-append on retry)
  6. CTA                   — from cta_registry.CTA_REGISTRY; idempotent
  7. Link branding         — delegates to link_service.brand_links_in_text()
  8. Length guard          — structured warning when output exceeds WA soft limit
  9. Metadata log          — structured INFO with event/cta_type/has_signature/length

All steps degrade gracefully: missing context keys → empty string; missing
settings record → FRIENDLY tone, signature on, no CTA.
"""
import logging

from apps.communications.utils.renderer import extract_placeholders, render_template
from apps.branding_adapter.cta_registry import build_cta
from apps.branding_adapter.link_service import brand_links_in_text

logger = logging.getLogger('apps.branding_adapter')

# WhatsApp Business API hard limit; 1600 is the soft-warn threshold.
_WA_SOFT_LIMIT = 1_600
_WA_HARD_LIMIT = 4_096

# Sentinel for reliable CTA idempotency detection.
# ZWSP (​) + LRM (‎): invisible in WhatsApp, not in any normal message
# body. Prepended to the CTA block on first application; checked before every
# subsequent append — so dynamic CTA values (payment links) and whitespace
# variance can never cause false negatives the way cta.strip()-in-message could.
#
# NOTE (item 1 — metadata log timing): the metadata log in step 9 captures the
# state at format_message() exit. If a downstream channel adapter rewrites the
# message further (e.g. truncates for a different gateway limit), the logged
# length will differ from what is ultimately delivered. Wire the log to the
# send result when that level of precision is needed.
_CTA_APPLIED_MARKER = '​‎'


# ── tone greeting registry ────────────────────────────────────────────────────
# Extend by adding a new key — no other changes required.

GREETING_REGISTRY: dict[str, str] = {
    'FORMAL':   'Dear {name},\n\n',
    'FRIENDLY': 'Hi {name}!\n\n',
    'MINIMAL':  '',
}


def _build_greeting(tone: str, context: dict) -> str:
    template = GREETING_REGISTRY.get(tone, GREETING_REGISTRY['FRIENDLY'])
    if not template:
        return ''
    name = context.get('member_name') or context.get('name') or ''
    return template.format(name=name)


# ── main adapter ──────────────────────────────────────────────────────────────

class WhatsAppBrandingAdapter:
    """
    Stateless formatter — all state from DB/cache via the services layer.

    Usage:
        msg = WhatsAppBrandingAdapter.format_message(
            event='membership.activated',
            content='Your membership is now active.',
            context={'member_name': 'Alice', 'phone': '+911234567890'},
            tenant=tenant,
        )
    """

    @staticmethod
    def format_message(event: str, content: str, context: dict, tenant) -> str:
        from apps.settings.whatsapp.services import WhatsAppSettingsService

        wa_settings = WhatsAppSettingsService.get_settings(tenant)
        tenant_id   = str(getattr(tenant, 'pk', ''))

        # 1. Template resolution — per-event override trumps MessageTemplate.content
        overrides    = (getattr(wa_settings, 'template_overrides', None) or {})
        template_str = overrides.get(event) or content

        # 2. Variable substitution + missing-var warning
        missing = extract_placeholders(template_str) - set(context.keys())
        if missing:
            logger.warning(
                "[WhatsApp] Message has unresolved placeholders",
                extra={
                    "reason":    "missing_template_vars",
                    "event":     event,
                    "tenant_id": tenant_id,
                    "missing":   sorted(missing),
                },
            )
        body = render_template(template_str, context)

        # 3. Tone greeting
        tone     = (getattr(wa_settings, 'tone', None) or 'FRIENDLY') if wa_settings else 'FRIENDLY'
        greeting = _build_greeting(tone, context)

        # 4. Assemble
        message = greeting + body

        # 5. Signature — idempotent: skip if already present (retry safety)
        sig_enabled = getattr(wa_settings, 'signature_enabled', True) if wa_settings else True
        brand_name  = getattr(tenant, 'name', '') or ''
        sig_line    = f'— {brand_name}'
        has_sig     = False
        if sig_enabled and brand_name and sig_line not in message:
            message += f'\n\n{sig_line}'
            has_sig = True
        elif sig_enabled and brand_name and sig_line in message:
            has_sig = True  # already present from prior format call

        # 6. CTA — idempotent via sentinel marker.
        # Sentinel check is robust against dynamic CTA values (payment links)
        # and whitespace variance that made cta.strip()-in-message unreliable.
        # Marker persists in the sent message (invisible to WA users) and is
        # detected on any retry call that passes the formatted output as content.
        cta_style = (getattr(wa_settings, 'cta_style', None) or 'NONE') if wa_settings else 'NONE'
        cta       = build_cta(cta_style, context)
        if cta and _CTA_APPLIED_MARKER not in message:
            message += _CTA_APPLIED_MARKER + cta

        # 7. Link branding (shared service — SMS/Email/PDF will reuse)
        message = brand_links_in_text(message, tenant)

        # 8. Length guard
        length = len(message)
        if length > _WA_HARD_LIMIT:
            logger.warning(
                "[WhatsApp] Message exceeds hard limit — will likely be rejected by gateway",
                extra={
                    "reason":    "message_too_long",
                    "event":     event,
                    "tenant_id": tenant_id,
                    "length":    length,
                    "limit":     _WA_HARD_LIMIT,
                },
            )
            message = message[:_WA_HARD_LIMIT]
        elif length > _WA_SOFT_LIMIT:
            logger.warning(
                "[WhatsApp] Message exceeds soft limit",
                extra={
                    "reason":    "message_long",
                    "event":     event,
                    "tenant_id": tenant_id,
                    "length":    length,
                    "limit":     _WA_SOFT_LIMIT,
                },
            )

        # 9. CTA traceability + message metadata — structured audit/analytics backbone.
        # cta_type tells the renewal engine exactly which CTA was sent, making
        # "which payment link did we send?" answerable without reading message text.
        logger.info(
            "[WhatsApp] Message formatted",
            extra={
                "reason":        "message_formatted",
                "event":         event,
                "cta_type":      cta_style if cta else "NONE",
                "has_signature": has_sig,
                "length":        len(message),
                "tenant_id":     tenant_id,
            },
        )

        return message
