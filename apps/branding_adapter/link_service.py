"""
Shared link branding service.

Centralises URL transformation so every channel (WhatsApp, SMS, Email, PDF)
goes through the same logic instead of implementing it inline.

When a tenant has white-label enabled AND a custom_domain configured on their
TenantBranding record, every link that passes through brand_link() has its
host replaced with the tenant's custom domain, preserving the original scheme,
path, and query string.

Example:
    https://platform.saas.com/payments/checkout/abc123/
    → https://app.mygym.com/payments/checkout/abc123/
"""
import re

_BARE_URL_RE = re.compile(r'https?://[^\s]+')
_HOST_RE     = re.compile(r'^(https?://)([^/?#]+)')


def brand_link(url: str, tenant) -> str:
    """
    Return url with the host replaced by the tenant's custom domain, when:
      - tenant has a TenantBranding record with whitelabel_enabled=True
      - AND that record has a non-empty custom_domain

    Returns url unchanged in all other cases. Never raises.
    """
    try:
        from apps.settings.branding.services import BrandingService
        branding = BrandingService.get_branding(tenant)
        if branding and branding.whitelabel_enabled and branding.custom_domain:
            custom_domain = branding.custom_domain.strip().rstrip('/')
            return _HOST_RE.sub(lambda m: f'{m.group(1)}{custom_domain}', url)
    except Exception:
        pass
    return url


def brand_links_in_text(text: str, tenant) -> str:
    """Apply brand_link() to every bare URL found in text."""
    return _BARE_URL_RE.sub(lambda m: brand_link(m.group(0), tenant), text)
