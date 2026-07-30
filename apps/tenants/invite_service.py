"""Create, validate and accept tenant invitations.

    raw_token, invite = create_invite(studio_name=..., subdomain=..., email=...)
    invite = get_usable_invite(raw_token)          # None if bad/expired/used
    tenant = accept_invite(raw_token, password)    # atomic

Design notes
------------
* create_invite() returns the raw token exactly once. It is never stored and
  cannot be recovered — reissuing means creating a new invite.

* accept_invite() is the only place a tenant is created from an invite, and it
  runs in a single transaction with select_for_update() on the invite row.
  Without that lock two concurrent accepts of the same token could both pass
  the usability check and provision two workspaces.

* Email delivery is deliberately OUTSIDE the creation transaction and never
  raises. An SMTP failure must not roll back a perfectly good invite; the
  outcome is recorded on the row instead.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.tenants.models import (
    InviteStatus,
    TenantInvite,
    generate_token,
    hash_token,
)

logger = logging.getLogger("apps.tenants.invites")

DEFAULT_EXPIRY_DAYS = 7


class InviteError(Exception):
    """Invite could not be created or accepted."""


def _expiry_days() -> int:
    return int(getattr(settings, "TENANT_INVITE_EXPIRY_DAYS", DEFAULT_EXPIRY_DAYS))


def build_invite_url(raw_token: str) -> str:
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    return f"{base}/invite/{raw_token}/"


def suggest_subdomain(studio_name: str) -> str:
    """Slug that is free right now. Not a reservation — accept re-checks."""
    from apps.core.models import Tenant

    base = slugify(studio_name)[:90] or "studio"
    candidate, n = base, 1
    while Tenant.objects.filter(subdomain=candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def create_invite(studio_name, email, subdomain=None, owner_name="",
                  invited_by=None, expiry_days=None):
    """Create a pending invite. Returns (raw_token, invite).

    The raw token is returned once and never persisted.
    """
    from apps.core.models import Tenant

    studio_name = (studio_name or "").strip()
    email = (email or "").strip().lower()

    if not studio_name:
        raise InviteError("Studio name is required.")
    if not email:
        raise InviteError("Email is required.")

    subdomain = (subdomain or "").strip().lower() or suggest_subdomain(studio_name)

    if Tenant.objects.filter(subdomain=subdomain).exists():
        raise InviteError(f"Subdomain '{subdomain}' is already taken.")
    if Tenant.objects.filter(name__iexact=studio_name).exists():
        raise InviteError(f"A tenant named '{studio_name}' already exists.")

    # A second live invite to the same subdomain would race at accept time.
    clash = TenantInvite.objects.filter(
        subdomain=subdomain, status=InviteStatus.PENDING,
        expires_at__gt=timezone.now(),
    ).first()
    if clash:
        raise InviteError(
            f"A pending invite for subdomain '{subdomain}' already exists "
            f"({clash.email}). Revoke it first."
        )

    raw_token = generate_token()
    days = expiry_days if expiry_days is not None else _expiry_days()

    invite = TenantInvite.objects.create(
        studio_name=studio_name,
        subdomain=subdomain,
        email=email,
        owner_name=(owner_name or "").strip(),
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timezone.timedelta(days=days),
        invited_by=invited_by,
    )
    return raw_token, invite


def get_usable_invite(raw_token: str):
    """Return the invite if this token can still be used, else None.

    Returns None rather than raising, and does not distinguish "unknown token"
    from "expired" to the caller, so the view cannot leak which invites exist.
    """
    if not raw_token:
        return None

    invite = TenantInvite.objects.filter(token_hash=hash_token(raw_token)).first()
    if invite is None or not invite.is_usable:
        return None
    return invite


def send_invite_email(invite, raw_token) -> bool:
    """Send the invite through the platform comms engine. Never raises."""
    from apps.communications.services import platform_comms

    try:
        sent = platform_comms.notify_platform(
            platform_comms.TENANT_INVITED,
            {
                "email": invite.email,
                "owner_name": invite.owner_name or "there",
                "studio_name": invite.studio_name,
                "invite_url": build_invite_url(raw_token),
                "expiry_days": str(invite.days_until_expiry or _expiry_days()),
            },
        )
    except Exception as exc:                       # pragma: no cover - defensive
        logger.exception("[Invites] Invite email raised")
        TenantInvite.objects.filter(pk=invite.pk).update(
            email_sent=False, email_error=str(exc)[:500]
        )
        return False

    error = "" if sent else (
        "notify_platform returned False — check that the platform tenant "
        "exists and seed_platform_comms has been run."
    )
    TenantInvite.objects.filter(pk=invite.pk).update(
        email_sent=sent, email_error=error
    )
    if not sent:
        logger.error("[Invites] Invite email not sent", extra={"invite": str(invite.pk)})
    return sent


@transaction.atomic
def accept_invite(raw_token: str, password: str, owner_name: str = ""):
    """Provision the tenant for this invite. Returns the Tenant.

    Everything here is one transaction: the invite is locked, re-validated,
    the tenant and Owner user are created, and the invite is marked accepted.
    If any step fails nothing is left behind — no half-made tenant, no invite
    burned without a workspace to show for it.
    """
    from apps.tenants.services import TenantService
    from apps.core.models import Tenant

    if not raw_token:
        raise InviteError("This invitation link is not valid.")
    if not password or len(password) < 12:
        raise InviteError("Password must be at least 12 characters.")

    # Lock the row so two concurrent accepts cannot both pass the check below.
    invite = (
        TenantInvite.objects.select_for_update()
        .filter(token_hash=hash_token(raw_token))
        .first()
    )
    if invite is None:
        raise InviteError("This invitation link is not valid.")
    if invite.status == InviteStatus.ACCEPTED:
        raise InviteError("This invitation has already been used.")
    if invite.status == InviteStatus.REVOKED:
        raise InviteError("This invitation has been revoked.")
    if invite.is_expired:
        raise InviteError("This invitation has expired. Ask for a new one.")

    # Re-check availability: the invite may have been issued days ago.
    if Tenant.objects.filter(subdomain=invite.subdomain).exists():
        raise InviteError(
            "That workspace address is no longer available. Ask for a new invite."
        )

    tenant = TenantService.create_tenant(
        name=invite.studio_name,
        subdomain=invite.subdomain,
        admin_email=invite.email,
        password=password,
    )

    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = timezone.now()
    invite.tenant = tenant
    if owner_name and not invite.owner_name:
        invite.owner_name = owner_name.strip()
    invite.save(update_fields=[
        "status", "accepted_at", "tenant", "owner_name", "updated_at",
    ])

    logger.info(
        "[Invites] Tenant provisioned from invite",
        extra={"tenant": tenant.subdomain, "invite": str(invite.pk)},
    )
    return tenant


def revoke_invite(invite) -> None:
    if invite.status != InviteStatus.PENDING:
        raise InviteError(f"Only pending invites can be revoked (this one is {invite.status}).")
    invite.status = InviteStatus.REVOKED
    invite.save(update_fields=["status", "updated_at"])
