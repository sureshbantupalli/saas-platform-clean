"""
CTA (call-to-action) registry — channel-agnostic definitions.

Each entry is a callable: (context: dict) -> str
Returns the full CTA string including leading newlines, or '' when
required context keys are absent.

Centralised here so WhatsApp, SMS, Email, and PDF channels all pull
from the same source without duplicating logic.

Extending:
    Register a new style by adding it to CTA_REGISTRY and the
    CTAStyle choices in apps/settings/whatsapp/models.py.
"""
from typing import Callable


def _cta_pay_now(context: dict) -> str:
    link = context.get('payment_link') or context.get('checkout_url', '')
    return f'\n\nClick here to pay: {link}' if link else ''


def _cta_confirm(context: dict) -> str:
    return '\n\nReply YES to confirm.'


def _cta_contact(context: dict) -> str:
    phone = context.get('support_phone') or context.get('phone', '')
    return f'\n\nCall us at {phone}' if phone else ''


CTA_REGISTRY: dict[str, Callable[[dict], str]] = {
    'PAY_NOW': _cta_pay_now,
    'CONFIRM': _cta_confirm,
    'CONTACT': _cta_contact,
    'NONE':    lambda _: '',
}


def build_cta(cta_style: str, context: dict) -> str:
    """Return the CTA string for cta_style. Returns '' for unknown styles."""
    handler = CTA_REGISTRY.get(cta_style)
    return handler(context) if handler else ''
