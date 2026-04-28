from django.core.cache import cache

from .models import TenantBranding

DEFAULTS = {
    'primary_color':   '#0d6efd',
    'secondary_color': '#6c757d',
    'login_title':     'Welcome back',
}

_CACHE_TTL = 300  # 5 minutes


def _cache_key(tenant_id):
    return f'branding:{tenant_id}'


# ── colour math helpers ───────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex_to_rgb_str(hex_color: str) -> str:
    """Return 'r, g, b' string for use in CSS rgba()."""
    return '{}, {}, {}'.format(*_hex_to_rgb(hex_color))


def _darken(hex_color: str, factor: float = 0.12) -> str:
    """Return a slightly darker shade of the given hex colour."""
    r, g, b = _hex_to_rgb(hex_color)
    return '#{:02x}{:02x}{:02x}'.format(
        max(0, int(r * (1 - factor))),
        max(0, int(g * (1 - factor))),
        max(0, int(b * (1 - factor))),
    )


# ── service ───────────────────────────────────────────────────────────────────

class BrandingService:

    @staticmethod
    def get_branding(tenant) -> TenantBranding | None:
        key = _cache_key(tenant.pk)
        sentinel = object()
        cached = cache.get(key, sentinel)
        if cached is not sentinel:
            return cached

        try:
            branding = TenantBranding.objects.select_related('tenant').get(tenant=tenant)
        except TenantBranding.DoesNotExist:
            branding = None

        cache.set(key, branding, _CACHE_TTL)
        return branding

    @staticmethod
    def get_css_vars(tenant) -> dict:
        """
        Return all CSS custom properties for this tenant.
        Includes hover and RGB variants for compositing.
        """
        branding = BrandingService.get_branding(tenant)
        if not branding or not branding.whitelabel_enabled:
            primary   = DEFAULTS['primary_color']
            secondary = DEFAULTS['secondary_color']
        else:
            primary   = branding.primary_color   or DEFAULTS['primary_color']
            secondary = branding.secondary_color or DEFAULTS['secondary_color']

        return {
            '--primary-color':     primary,
            '--primary-rgb':       _hex_to_rgb_str(primary),
            '--primary-hover':     _darken(primary),
            '--secondary-color':   secondary,
            '--secondary-hover':   _darken(secondary),
        }

    @staticmethod
    def is_enabled(tenant) -> bool:
        branding = BrandingService.get_branding(tenant)
        return bool(branding and branding.whitelabel_enabled)

    @staticmethod
    def save_branding(tenant, data: dict, logo=None, favicon=None) -> TenantBranding:
        branding, _ = TenantBranding.objects.get_or_create(tenant=tenant)

        for field in ('primary_color', 'secondary_color', 'login_title', 'custom_css', 'custom_domain'):
            if field in data:
                setattr(branding, field, data[field])

        if logo is not None:
            branding.logo = logo
        if favicon is not None:
            branding.favicon = favicon

        branding.full_clean(exclude=['tenant'])
        branding.save()
        cache.delete(_cache_key(tenant.pk))
        return branding

    @staticmethod
    def reset_branding(tenant) -> None:
        TenantBranding.objects.filter(tenant=tenant).update(
            primary_color   = DEFAULTS['primary_color'],
            secondary_color = DEFAULTS['secondary_color'],
            login_title     = '',
            custom_css      = '',
        )
        cache.delete(_cache_key(tenant.pk))

    @staticmethod
    def generate_palette_from_logo(file) -> dict:
        """
        Extract a colour palette from a logo file.
        Returns {primary_color, secondary_color, low_confidence}.
        Never writes to the DB.
        """
        from .color_extraction_service import ColorExtractionService
        return ColorExtractionService.extract_from_file(file)

    @staticmethod
    def invalidate(tenant) -> None:
        cache.delete(_cache_key(tenant.pk))
