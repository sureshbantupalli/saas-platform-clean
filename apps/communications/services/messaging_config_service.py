"""Resolves per-tenant SMS / WhatsApp credentials.

Mirrors payments/services/config_service.py: an active TenantMessagingConfig
wins; otherwise global environment variables are used as a development
fallback; otherwise nothing is returned and the adapter degrades to logging.

    get_messaging_config(tenant, MessagingProvider.MSG91) -> config or None

The returned object always exposes the same four attributes — api_key,
sender_id, template_id, template_lang — whether it came from the database or
from the environment, so adapters do not need to care which.

On the env fallback
-------------------
It exists so local development and the test-suite run without seeding a
config row, and so the single-tenant deployment keeps working unchanged. It is
NOT appropriate once a second tenant exists: env vars are global, so every
tenant without its own row would send under whichever credentials happen to be
in the environment. `warn_if_env_fallback_is_ambiguous()` exists to make that
situation visible rather than silent.
"""

import logging
import os
from types import SimpleNamespace

from django.conf import settings

logger = logging.getLogger("apps.communications.config")


def _setting(name: str, default: str = "") -> str:
    """Django settings first, then environment. Same order as the adapters."""
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, default)
    return (value or "").strip()


def _env_config(provider: str):
    """Build a config-shaped object from global env vars, or None."""
    from apps.communications.models import MessagingProvider

    if provider == MessagingProvider.MSG91:
        api_key = _setting("MSG91_AUTH_KEY")
        template_id = _setting("MSG91_DLT_TE_ID")
        if not (api_key and template_id):
            return None
        return SimpleNamespace(
            api_key=api_key,
            sender_id=_setting("MSG91_SENDER_ID"),
            template_id=template_id,
            template_lang="",
            is_active=True,
            _source="env",
        )

    if provider == MessagingProvider.WHATSAPP_CLOUD:
        api_key = _setting("WHATSAPP_ACCESS_TOKEN")
        sender_id = _setting("WHATSAPP_PHONE_NUMBER_ID")
        if not (api_key and sender_id):
            return None
        return SimpleNamespace(
            api_key=api_key,
            sender_id=sender_id,
            template_id=_setting("WHATSAPP_TEMPLATE_NAME"),
            template_lang=_setting("WHATSAPP_TEMPLATE_LANG"),
            is_active=True,
            _source="env",
        )

    return None


def get_messaging_config(tenant, provider: str):
    """Return credentials for this tenant and provider, or None.

    Never raises. The adapters call this from __init__, which must not blow up
    — communication_service constructs every adapter on every send, so one bad
    lookup would take the other channels down with it.
    """
    from apps.communications.models import TenantMessagingConfig

    if tenant is not None:
        try:
            config = TenantMessagingConfig.objects.filter(
                tenant=tenant, provider=provider, is_active=True
            ).first()
        except Exception:
            # A missing migration or a broken decrypt must not break sending
            # for tenants whose credentials are fine.
            logger.exception(
                "[Comms] Failed to read tenant messaging config",
                extra={"provider": provider},
            )
            config = None

        if config:
            return config

    return _env_config(provider)


def warn_if_env_fallback_is_ambiguous(tenant, provider: str, config) -> None:
    """Log loudly when env credentials are used and more than one tenant exists.

    With several tenants, falling back to global env vars means sending under
    someone else's sender header — a TRAI/Meta compliance problem rather than a
    cosmetic one. This does not block the send; it makes the situation findable.
    """
    if config is None or getattr(config, "_source", "") != "env":
        return

    from apps.core.models import Tenant
    from apps.core.platform import exclude_platform

    try:
        tenant_count = exclude_platform(Tenant.objects.all()).count()
    except Exception:
        return

    if tenant_count > 1:
        logger.error(
            "[Comms] Falling back to GLOBAL env credentials with %d tenants "
            "configured — this tenant's messages will be sent under whichever "
            "credentials are in the environment. Configure a "
            "TenantMessagingConfig for this tenant.",
            tenant_count,
            extra={
                "provider": provider,
                "tenant_id": str(getattr(tenant, "pk", "")),
            },
        )
