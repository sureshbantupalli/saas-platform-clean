"""
BrandingAdapter — normalised branding payload for any output channel.

Reads from BrandingService (handles caching + tenant isolation).
Computes a contrast-safe text colour. Never touches templates or DB directly.

Designed for reuse across email, PDF, WhatsApp, and future channels —
callers get a plain dict and decide how to render it.
"""
from django.conf import settings

from apps.settings.branding.services import BrandingService, DEFAULTS, _darken, _hex_to_rgb


# ── WCAG contrast helpers ─────────────────────────────────────────────────────

def _to_linear(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _relative_luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * _to_linear(r) + 0.7152 * _to_linear(g) + 0.0722 * _to_linear(b)


def _contrast_text_color(hex_color: str) -> str:
    """Return '#ffffff' or '#000000' — whichever reads better on hex_color background."""
    r, g, b = _hex_to_rgb(hex_color)
    lum = _relative_luminance(r, g, b)
    contrast_white = 1.05 / (lum + 0.05)
    contrast_black = (lum + 0.05) / 0.05
    return '#ffffff' if contrast_white >= contrast_black else '#000000'


# ── logo URL helper ───────────────────────────────────────────────────────────

def get_logo_url(branding, request=None) -> str:
    """
    Build the best possible absolute URL for the tenant logo.

    Priority:
      1. SITE_URL setting (preferred for CDN / production overrides)
      2. request.build_absolute_uri() (accurate for the current HTTP scheme/host)
      3. Empty string (graceful — no crash, image hidden in template)

    Guarantees no double slashes regardless of how SITE_URL is configured.
    """
    if not branding or not branding.logo:
        return ''
    try:
        relative = branding.logo.url  # e.g. '/media/tenant/logos/logo.png'
    except Exception:
        return ''

    site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
    if site_url:
        return f'{site_url}/{relative.lstrip("/")}'

    if request is not None:
        return request.build_absolute_uri(relative)

    return ''  # no way to make it absolute; template hides it gracefully


# ── adapter ───────────────────────────────────────────────────────────────────

class BrandingAdapter:
    """
    Single source of truth for per-tenant branding data in non-web contexts.

    Usage:
        ctx = BrandingAdapter.get_branding_context(tenant)
        # ctx = {
        #   'logo_url':        'https://example.com/media/...',
        #   'primary_color':   '#0d6efd',
        #   'secondary_color': '#6c757d',
        #   'primary_hover':   '#0b5ed7',
        #   'text_color':      '#ffffff',
        #   'brand_name':      'Acme Gym',
        # }
    """

    @staticmethod
    def get_branding_context(tenant, request=None) -> dict:
        """
        Return a normalised branding dict. Always succeeds — falls back to
        platform defaults when no branding record exists or whitelabel is off.

        Pass request when available so logo URLs can be made absolute via
        request.build_absolute_uri() if SITE_URL is not configured.
        """
        branding   = BrandingService.get_branding(tenant)
        is_enabled = BrandingService.is_enabled(tenant)

        if not is_enabled:
            primary   = DEFAULTS['primary_color']
            secondary = DEFAULTS['secondary_color']
            logo_url  = ''
        else:
            primary   = (branding and branding.primary_color)   or DEFAULTS['primary_color']
            secondary = (branding and branding.secondary_color) or DEFAULTS['secondary_color']
            logo_url  = get_logo_url(branding, request)

        return {
            'logo_url':        logo_url,
            'primary_color':   primary,
            'secondary_color': secondary,
            'primary_hover':   _darken(primary),
            'text_color':      _contrast_text_color(primary),
            'brand_name':      getattr(tenant, 'name', ''),
        }
