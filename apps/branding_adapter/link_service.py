"""
Shared link branding service.

Centralises URL transformation so every channel (WhatsApp, SMS, Email, PDF)
goes through the same logic instead of implementing it inline.

Current behaviour: no-op (passes URLs through unchanged).
Extension point: when Tenant gains a `custom_domain` field, replace the
platform host with the tenant domain here — all channels benefit automatically.
"""
import re

_BARE_URL_RE = re.compile(r'https?://[^\s]+')


def brand_link(url: str, tenant) -> str:
    """
    Return a (potentially rewritten) version of url for the given tenant.

    When white-label is enabled and tenant.custom_domain exists, this is
    where the platform domain gets swapped out. Until then, returns url as-is.
    """
    try:
        from apps.settings.branding.services import BrandingService
        if not BrandingService.is_enabled(tenant):
            return url
        # TODO: when Tenant.custom_domain field is added:
        #   custom_domain = getattr(tenant, 'custom_domain', '')
        #   if custom_domain:
        #       return re.sub(r'https?://[^/]+', f'https://{custom_domain}', url)
    except Exception:
        pass
    return url


def brand_links_in_text(text: str, tenant) -> str:
    """Apply brand_link() to every bare URL found in text."""
    return _BARE_URL_RE.sub(lambda m: brand_link(m.group(0), tenant), text)
