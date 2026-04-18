"""
Payment config service — resolves per-tenant gateway credentials.

get_active_payment_config(tenant, provider) returns an object with:
    .key_id         — Razorpay public key (safe to expose to frontend)
    .key_secret     — Razorpay private key (NEVER expose in API responses)
    .webhook_secret — Razorpay webhook secret (NEVER expose in API responses)

Falls back to global Django settings when no tenant config exists (dev convenience).
In production, every tenant must configure their own credentials.
"""
from types import SimpleNamespace


class PaymentConfigError(Exception):
    pass


def get_active_payment_config(tenant, provider: str = "razorpay"):
    """
    Returns the active TenantPaymentConfig for the given tenant+provider,
    or a SimpleNamespace populated from global settings as a dev fallback.

    Raises PaymentConfigError if neither exists.
    """
    from apps.payments.models import TenantPaymentConfig

    config = TenantPaymentConfig.objects.filter(
        tenant=tenant, provider=provider, is_active=True
    ).first()

    if config:
        return config

    # Dev fallback: global settings (set in config/settings/base.py or env vars)
    from django.conf import settings as django_settings

    if provider == "razorpay":
        key_id         = getattr(django_settings, "RAZORPAY_KEY_ID",         "")
        key_secret     = getattr(django_settings, "RAZORPAY_KEY_SECRET",     "")
        webhook_secret = getattr(django_settings, "RAZORPAY_WEBHOOK_SECRET", "")
        placeholder_values = {"rzp_test_placeholder", "placeholder_secret", "webhook_placeholder", ""}
        if key_id not in placeholder_values and key_secret not in placeholder_values:
            return SimpleNamespace(
                key_id=key_id,
                key_secret=key_secret,
                webhook_secret=webhook_secret,
            )

    raise PaymentConfigError(
        "No active Razorpay configuration found for this tenant. "
        "Go to Settings → Payments to configure your Razorpay credentials."
    )
