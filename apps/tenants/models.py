# The Tenant model itself is defined in apps.core.models.
"""Tenant invitation.

Lets a studio owner provision their own workspace instead of someone running
`provision_tenant` over SSH for them.

Security posture
----------------
The token is treated like a password-reset token, because that is what it is:
a bearer credential that creates an account with Owner permissions.

  * Only a SHA-256 HASH of the token is stored. A database leak therefore does
    not hand over usable invites — the same reason Django never stores raw
    password-reset tokens.
  * The raw token is returned exactly once, by create_invite(), and only ever
    goes into the invite email.
  * Single use: accepted_at is set inside the same transaction that creates the
    tenant, so one token cannot provision two workspaces.
  * Expiry is enforced in code on every lookup, not merely displayed.
"""

import hashlib
import secrets

from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel

# 32 bytes → 43 URL-safe characters. Comfortably beyond guessing.
TOKEN_BYTES = 32


def generate_token() -> str:
    """Return a fresh raw token. Store only hash_token() of this."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """Hash for storage and lookup.

    Plain SHA-256 rather than a password hash on purpose: the token already
    carries 256 bits of entropy so it is not brute-forceable and gains nothing
    from a slow KDF, and a fast hash keeps lookup a single indexed query.
    """
    return hashlib.sha256((raw_token or "").encode()).hexdigest()


class InviteStatus(models.TextChoices):
    PENDING  = "PENDING",  "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    REVOKED  = "REVOKED",  "Revoked"


class TenantInvite(BaseModel):
    """An invitation for one studio to provision its own workspace."""

    # What gets created when this invite is accepted.
    studio_name = models.CharField(
        max_length=255,
        help_text="Becomes the Tenant name.",
    )
    subdomain = models.SlugField(
        max_length=100,
        help_text="Becomes the Tenant subdomain. Must still be free at accept time.",
    )
    email = models.EmailField(
        help_text="Invitee's address. Becomes the Owner user's login.",
    )
    owner_name = models.CharField(
        max_length=255, blank=True,
        help_text="Used to address the invite email.",
    )

    # Credential. Never stores the raw token — see module docstring.
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)

    status = models.CharField(
        max_length=20, choices=InviteStatus.choices, default=InviteStatus.PENDING
    )
    expires_at = models.DateTimeField(db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Set on acceptance so an invite can be traced to what it created.
    tenant = models.ForeignKey(
        "core.Tenant",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="invites",
    )

    invited_by = models.ForeignKey(
        "accounts.User",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_tenant_invites",
    )

    # Delivery is best-effort and must never roll back invite creation, so the
    # outcome is recorded rather than raised.
    email_sent = models.BooleanField(default=False)
    email_error = models.TextField(blank=True)

    class Meta:
        db_table = "tenant_invites"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        return f"Invite for {self.studio_name} <{self.email}> [{self.status}]"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        """Pending, unexpired, not already accepted or revoked."""
        return self.status == InviteStatus.PENDING and not self.is_expired

    @property
    def days_until_expiry(self) -> int:
        remaining = self.expires_at - timezone.now()
        return max(0, remaining.days)
