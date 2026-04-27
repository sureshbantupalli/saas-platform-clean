"""
WhatsAppBrandingAdapter — formats plain-text WhatsApp messages for a tenant.

Pipeline (in order):
  1. Template resolution  — use per-event override if configured, else raw content
  2. Variable substitution — {{key}} placeholders replaced from context
  3. Tone greeting         — prepended based on FORMAL / FRIENDLY / MINIMAL
  4. Body
  5. Signature             — appended when signature_enabled (configurable)
  6. CTA                   — PAY_NOW / CONFIRM / CONTACT / NONE
  7. Link branding         — if whitelabel_enabled, domain-prefixes bare links

All steps degrade gracefully: missing context keys render as empty strings;
missing settings fall back to FRIENDLY tone, no signature, no CTA.
"""
import re

from apps.communications.utils.renderer import render_template


# ── variable substitution ─────────────────────────────────────────────────────

def _render(template_str: str, context: dict) -> str:
    """Render {{key}} placeholders from context. Missing keys → empty string."""
    return render_template(template_str, context)


# ── tone greeting ─────────────────────────────────────────────────────────────

_GREETING = {
    'FORMAL':   'Dear {name},\n\n',
    'FRIENDLY': 'Hi {name}!\n\n',
    'MINIMAL':  '',
}


def _build_greeting(tone: str, context: dict) -> str:
    template = _GREETING.get(tone, _GREETING['FRIENDLY'])
    if not template:
        return ''
    name = context.get('member_name') or context.get('name') or ''
    return template.format(name=name)


# ── CTA ───────────────────────────────────────────────────────────────────────

def _build_cta(cta_style: str, context: dict) -> str:
    if cta_style == 'PAY_NOW':
        link = context.get('payment_link') or context.get('checkout_url', '')
        if link:
            return f'\n\nClick here to pay: {link}'
        return ''
    if cta_style == 'CONFIRM':
        return '\n\nReply YES to confirm.'
    if cta_style == 'CONTACT':
        phone = context.get('support_phone') or context.get('phone', '')
        if phone:
            return f'\n\nCall us at {phone}'
        return ''
    return ''  # NONE or unknown


# ── link branding ─────────────────────────────────────────────────────────────

_BARE_URL_RE = re.compile(r'https?://[^\s]+')


def _brand_links(text: str, tenant) -> str:
    """
    When white-label is enabled and the tenant has a custom domain, prefix bare
    links with the tenant domain. Currently a no-op placeholder — the hook is
    in place so implementors can extend it without touching the main pipeline.
    """
    try:
        from apps.settings.branding.services import BrandingService
        if not BrandingService.is_enabled(tenant):
            return text
        # Future: replace platform domain with tenant.custom_domain when that
        # field exists. For now return text unchanged.
    except Exception:
        pass
    return text


# ── main adapter ─────────────────────────────────────────────────────────────

class WhatsAppBrandingAdapter:
    """
    Stateless formatter. All state comes from the DB/cache via the services layer.

    Usage:
        message = WhatsAppBrandingAdapter.format_message(
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

        # 1. Template resolution — per-event override trumps MessageTemplate.content
        overrides = getattr(wa_settings, 'template_overrides', {}) or {}
        template_str = overrides.get(event) or content

        # 2. Variable substitution
        body = _render(template_str, context)

        # 3. Tone greeting
        tone = getattr(wa_settings, 'tone', 'FRIENDLY') if wa_settings else 'FRIENDLY'
        greeting = _build_greeting(tone, context)

        # 4. Assemble greeting + body
        message = greeting + body

        # 5. Signature
        sig_enabled = getattr(wa_settings, 'signature_enabled', True) if wa_settings else True
        if sig_enabled:
            brand_name = getattr(tenant, 'name', '') or ''
            if brand_name:
                message += f'\n\n— {brand_name}'

        # 6. CTA
        cta_style = getattr(wa_settings, 'cta_style', 'NONE') if wa_settings else 'NONE'
        message += _build_cta(cta_style, context)

        # 7. Link branding
        message = _brand_links(message, tenant)

        return message
