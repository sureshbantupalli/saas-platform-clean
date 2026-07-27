"""Resolver for the internal ANJASI platform tenant.

ANJASI needs to send its own messages — onboarding a new studio, invoices,
service notices — but every communications model (``MessageTemplate``,
``TriggerRule``, ``CommunicationLog``) is tenant-scoped, so there is no
"from the platform" concept in the engine.

Rather than build a parallel platform-messaging stack, ANJASI is represented
as an ordinary tenant flagged ``is_platform=True``. Platform templates,
trigger rules, rate limiting, logging and retry then all work unchanged.

The trade-off is that a synthetic tenant gets swept into any job that loops
over tenants, so those jobs exclude it explicitly — see ``exclude_platform``.
"""

from django.conf import settings

PLATFORM_TENANT_NAME = getattr(settings, "PLATFORM_TENANT_NAME", "ANJASI")
PLATFORM_TENANT_SUBDOMAIN = getattr(settings, "PLATFORM_TENANT_SUBDOMAIN", "anjasi")


class PlatformTenantMissing(RuntimeError):
    """Raised when the platform tenant has not been provisioned.

    Deliberately loud: silently skipping a platform message would mean an
    invoice or onboarding email never sends and nobody finds out.
    """


def get_platform_tenant():
    """Return the ANJASI tenant row.

    Not cached — a module-level cache would hold a stale object across the
    test-suite's transaction rollbacks, and this is called at most once per
    platform message.
    """
    from apps.core.models import Tenant

    tenant = Tenant.objects.filter(is_platform=True).first()
    if tenant is None:
        raise PlatformTenantMissing(
            "No platform tenant exists. Run: manage.py ensure_platform_tenant"
        )
    return tenant


def get_platform_tenant_or_none():
    """Same as ``get_platform_tenant`` but returns None when absent.

    For callers where platform messaging is optional and must not break the
    surrounding operation.
    """
    try:
        return get_platform_tenant()
    except PlatformTenantMissing:
        return None


def exclude_platform(queryset):
    """Drop the platform tenant from a tenant queryset.

    Used by batch jobs that loop over tenants (renewals, revenue nudges,
    comms seeding). The platform tenant has no members, so including it is
    wasted work at best and seeds studio-shaped defaults into ANJASI at worst.
    """
    return queryset.exclude(is_platform=True)
