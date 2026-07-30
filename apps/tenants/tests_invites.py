"""Tests for invite-link onboarding.

This is the only unauthenticated path that can create a tenant with an Owner
account, so the emphasis is on the security properties rather than the happy
path: the raw token is never stored, a token cannot be reused, expiry and
revocation are enforced on lookup rather than merely displayed, and the view
does not reveal which invites exist.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Tenant
from apps.tenants.invite_service import (
    InviteError,
    accept_invite,
    create_invite,
    get_usable_invite,
    revoke_invite,
    suggest_subdomain,
)
from apps.tenants.models import InviteStatus, TenantInvite, hash_token

User = get_user_model()
GOOD_PASSWORD = "correct-horse-battery-staple-42"


def _seed_permissions():
    """TenantService assigns permissions by module; none exist in a fresh test DB."""
    from apps.authority.models import PermissionAction
    for module in ["CORE", "MEMBERS", "CRM"]:
        for action in ["view", "create"]:
            PermissionAction.objects.get_or_create(module=module, action=action)


class TokenStorageTests(TestCase):
    def test_raw_token_is_never_stored(self):
        """A database leak must not hand over usable invites."""
        raw, invite = create_invite(studio_name="Setu Yoga", email="o@setu.com")

        self.assertNotEqual(invite.token_hash, raw)
        self.assertEqual(invite.token_hash, hash_token(raw))

        # The raw value appears in no column of the row.
        row = TenantInvite.objects.filter(pk=invite.pk).values().first()
        self.assertNotIn(raw, " ".join(str(v) for v in row.values()))

    def test_lookup_is_by_hash(self):
        raw, invite = create_invite(studio_name="Setu Yoga", email="o@setu.com")
        self.assertEqual(get_usable_invite(raw).pk, invite.pk)
        self.assertIsNone(get_usable_invite(invite.token_hash))
        self.assertIsNone(get_usable_invite("not-a-real-token"))
        self.assertIsNone(get_usable_invite(""))


class UsabilityTests(TestCase):
    def setUp(self):
        self.raw, self.invite = create_invite(
            studio_name="Setu Yoga", email="o@setu.com"
        )

    def test_expired_invite_is_unusable(self):
        self.invite.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        self.invite.save(update_fields=["expires_at"])
        self.assertIsNone(get_usable_invite(self.raw))

    def test_revoked_invite_is_unusable(self):
        revoke_invite(self.invite)
        self.assertIsNone(get_usable_invite(self.raw))

    def test_only_pending_invites_can_be_revoked(self):
        revoke_invite(self.invite)
        with self.assertRaises(InviteError):
            revoke_invite(self.invite)


class CreateInviteTests(TestCase):
    def test_rejects_duplicate_subdomain_of_existing_tenant(self):
        Tenant.objects.create(name="Existing", subdomain="setu-yoga")
        with self.assertRaises(InviteError):
            create_invite(studio_name="Setu Yoga", email="o@setu.com",
                          subdomain="setu-yoga")

    def test_rejects_a_second_pending_invite_for_the_same_subdomain(self):
        """Two live invites for one subdomain would race at accept time."""
        create_invite(studio_name="Setu Yoga", email="a@setu.com", subdomain="setu")
        with self.assertRaises(InviteError):
            create_invite(studio_name="Other", email="b@other.com", subdomain="setu")

    def test_allows_reuse_of_a_subdomain_once_the_invite_is_revoked(self):
        _, first = create_invite(studio_name="Setu", email="a@setu.com",
                                 subdomain="setu")
        revoke_invite(first)
        raw, second = create_invite(studio_name="Setu Two", email="b@setu.com",
                                    subdomain="setu")
        self.assertIsNotNone(raw)

    def test_suggest_subdomain_avoids_collisions(self):
        Tenant.objects.create(name="Setu Yoga", subdomain="setu-yoga")
        self.assertEqual(suggest_subdomain("Setu Yoga"), "setu-yoga-2")

    def test_requires_studio_name_and_email(self):
        with self.assertRaises(InviteError):
            create_invite(studio_name="", email="o@setu.com")
        with self.assertRaises(InviteError):
            create_invite(studio_name="Setu", email="")


class AcceptInviteTests(TestCase):
    def setUp(self):
        _seed_permissions()
        self.raw, self.invite = create_invite(
            studio_name="Setu Yoga", email="owner@setu.com", subdomain="setu"
        )

    def test_creates_tenant_and_owner_user(self):
        tenant = accept_invite(self.raw, GOOD_PASSWORD)

        self.assertEqual(tenant.subdomain, "setu")
        user = User.objects.get(email="owner@setu.com")
        self.assertEqual(user.tenant, tenant)
        self.assertEqual(user.role.name, "Owner")
        self.assertTrue(user.check_password(GOOD_PASSWORD))

    def test_marks_the_invite_used_and_links_the_tenant(self):
        tenant = accept_invite(self.raw, GOOD_PASSWORD)
        self.invite.refresh_from_db()

        self.assertEqual(self.invite.status, InviteStatus.ACCEPTED)
        self.assertIsNotNone(self.invite.accepted_at)
        self.assertEqual(self.invite.tenant, tenant)

    def test_token_is_single_use(self):
        """The core guarantee — one invite, one workspace."""
        accept_invite(self.raw, GOOD_PASSWORD)
        with self.assertRaises(InviteError):
            accept_invite(self.raw, GOOD_PASSWORD)
        self.assertEqual(Tenant.objects.filter(subdomain="setu").count(), 1)

    def test_rejects_expired_token(self):
        self.invite.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        self.invite.save(update_fields=["expires_at"])
        with self.assertRaises(InviteError):
            accept_invite(self.raw, GOOD_PASSWORD)

    def test_rejects_short_password(self):
        with self.assertRaises(InviteError):
            accept_invite(self.raw, "short")
        self.assertFalse(Tenant.objects.filter(subdomain="setu").exists())

    def test_rejects_subdomain_taken_since_the_invite_was_issued(self):
        Tenant.objects.create(name="Someone Else", subdomain="setu")
        with self.assertRaises(InviteError):
            accept_invite(self.raw, GOOD_PASSWORD)

    def test_failure_leaves_nothing_behind(self):
        """Atomicity: no half-made tenant, and the invite is not burned."""
        with patch(
            "apps.tenants.services.TenantService.create_tenant",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                accept_invite(self.raw, GOOD_PASSWORD)

        self.invite.refresh_from_db()
        self.assertEqual(self.invite.status, InviteStatus.PENDING)
        self.assertFalse(Tenant.objects.filter(subdomain="setu").exists())
        self.assertFalse(User.objects.filter(email="owner@setu.com").exists())


class AcceptViewTests(TestCase):
    def setUp(self):
        _seed_permissions()
        self.raw, self.invite = create_invite(
            studio_name="Setu Yoga", email="owner@setu.com", subdomain="setu"
        )
        self.url = reverse("tenants:invite_accept", args=[self.raw])

    def test_get_renders_the_setup_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Setu Yoga")
        self.assertContains(resp, "owner@setu.com")

    def test_post_provisions_and_redirects(self):
        resp = self.client.post(self.url, {
            "password": GOOD_PASSWORD,
            "password_confirm": GOOD_PASSWORD,
            "owner_name": "Suresh",
        })
        self.assertRedirects(resp, reverse("tenants:invite_done"))
        self.assertTrue(Tenant.objects.filter(subdomain="setu").exists())

    def test_mismatched_passwords_do_not_provision(self):
        resp = self.client.post(self.url, {
            "password": GOOD_PASSWORD, "password_confirm": "something-else-entirely",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Tenant.objects.filter(subdomain="setu").exists())

    def test_weak_password_is_rejected_by_djangos_validators(self):
        resp = self.client.post(self.url, {
            "password": "password123", "password_confirm": "password123",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Tenant.objects.filter(subdomain="setu").exists())

    def test_unknown_token_gets_the_generic_page(self):
        resp = self.client.get(reverse("tenants:invite_accept", args=["nope"]))
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "not valid", status_code=400)

    def test_expired_and_unknown_tokens_are_indistinguishable(self):
        """The response must not reveal which invites exist."""
        self.invite.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        self.invite.save(update_fields=["expires_at"])

        expired = self.client.get(self.url)
        unknown = self.client.get(reverse("tenants:invite_accept", args=["nope"]))

        self.assertEqual(expired.status_code, unknown.status_code)
        self.assertEqual(expired.content, unknown.content)

    def test_used_token_cannot_provision_a_second_workspace(self):
        self.client.post(self.url, {
            "password": GOOD_PASSWORD, "password_confirm": GOOD_PASSWORD,
        })
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Tenant.objects.filter(subdomain="setu").count(), 1)

    def test_rate_limited_after_repeated_attempts(self):
        from django.core.cache import cache
        cache.clear()
        bad = reverse("tenants:invite_accept", args=["nope"])
        for _ in range(10):
            self.client.get(bad)
        self.assertEqual(self.client.get(bad).status_code, 429)
        cache.clear()


class CreateInviteCommandTests(TestCase):
    def test_creates_invite_and_prints_link_without_sending(self):
        from io import StringIO
        out = StringIO()
        call_command("create_tenant_invite", "--studio", "Setu Yoga",
                     "--email", "owner@setu.com", "--no-email", stdout=out)

        output = out.getvalue()
        self.assertIn("/invite/", output)
        invite = TenantInvite.objects.get()
        self.assertEqual(invite.email, "owner@setu.com")
        self.assertFalse(invite.email_sent)

    def test_dry_run_creates_nothing(self):
        from io import StringIO
        call_command("create_tenant_invite", "--studio", "Setu", "--email",
                     "o@setu.com", "--dry-run", stdout=StringIO())
        self.assertFalse(TenantInvite.objects.exists())

    def test_reports_a_taken_subdomain_as_a_command_error(self):
        from io import StringIO
        Tenant.objects.create(name="Existing", subdomain="setu")
        with self.assertRaises(CommandError):
            call_command("create_tenant_invite", "--studio", "Setu", "--email",
                         "o@setu.com", "--subdomain", "setu", stdout=StringIO())

    def test_email_failure_does_not_lose_the_invite(self):
        """An SMTP problem must not destroy a valid invitation."""
        from io import StringIO
        out, err = StringIO(), StringIO()
        with patch("apps.tenants.invite_service.send_invite_email", return_value=False):
            call_command("create_tenant_invite", "--studio", "Setu Yoga",
                         "--email", "o@setu.com", stdout=out, stderr=err)
        self.assertTrue(TenantInvite.objects.exists())
