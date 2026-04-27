"""
WhatsAppSettingsService — cached read/write for TenantWhatsAppSettings.

Cache TTL mirrors BrandingService (5 minutes) so changes propagate quickly.
"""
from django.core.cache import cache

_CACHE_TTL = 300


def _cache_key(tenant_pk) -> str:
    return f'wa_settings:{tenant_pk}'


class WhatsAppSettingsService:

    @staticmethod
    def get_settings(tenant):
        """Return TenantWhatsAppSettings for tenant, or None if not configured."""
        key = _cache_key(tenant.pk)
        cached = cache.get(key)
        if cached is not None:
            return cached
        from apps.settings.whatsapp.models import TenantWhatsAppSettings
        try:
            obj = TenantWhatsAppSettings.objects.get(tenant=tenant)
        except TenantWhatsAppSettings.DoesNotExist:
            obj = None
        cache.set(key, obj, _CACHE_TTL)
        return obj

    @staticmethod
    def save_settings(tenant, data: dict):
        """Upsert WhatsApp settings from a dict of field values. Invalidates cache."""
        from apps.settings.whatsapp.models import TenantWhatsAppSettings
        obj, _ = TenantWhatsAppSettings.objects.get_or_create(tenant=tenant)
        allowed = {'tone', 'signature_enabled', 'cta_style', 'template_overrides'}
        for field, value in data.items():
            if field in allowed:
                setattr(obj, field, value)
        obj.save()
        cache.delete(_cache_key(tenant.pk))
        return obj

    @staticmethod
    def invalidate(tenant) -> None:
        cache.delete(_cache_key(tenant.pk))
