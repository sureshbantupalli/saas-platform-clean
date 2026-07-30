"""Tests for the seed_platform_comms management command.

The point of this command is to close the gap where platform messaging was
plumbed but silent — the platform tenant existed with zero templates, so
notify_platform() found no TriggerRule and sent nothing. These tests pin that
the seeded data actually makes the path fire, and pin the constraints that
would otherwise fail only at send time.
"""

from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.communications.models import Channel, MessageTemplate, TriggerRule
from apps.communications.services import platform_comms
from apps.communications.management.commands.seed_platform_comms import (
    PLATFORM_TEMPLATES,
)
from apps.core.models import Tenant


class SeedPlatformCommsTests(TestCase):
    def setUp(self):
        self.platform = Tenant.objects.create(
            name="ANJASI", subdomain="anjasi", is_platform=True
        )

    def test_seeds_a_template_and_rule_for_every_platform_event(self):
        call_command("seed_platform_comms")

        templates = MessageTemplate.base_objects.filter(tenant=self.platform)
        rules = TriggerRule.base_objects.filter(tenant=self.platform)

        self.assertEqual(templates.count(), len(PLATFORM_TEMPLATES))
        self.assertEqual(rules.count(), len(PLATFORM_TEMPLATES))

    def test_is_idempotent(self):
        """Safe to run on every deploy."""
        call_command("seed_platform_comms")
        call_command("seed_platform_comms")

        self.assertEqual(
            MessageTemplate.base_objects.filter(tenant=self.platform).count(),
            len(PLATFORM_TEMPLATES),
        )
        self.assertEqual(
            TriggerRule.base_objects.filter(tenant=self.platform).count(),
            len(PLATFORM_TEMPLATES),
        )

    def test_does_not_overwrite_edits(self):
        """Content edited in the admin must survive a re-run."""
        call_command("seed_platform_comms")
        tpl = MessageTemplate.base_objects.filter(tenant=self.platform).first()
        tpl.subject = "Edited by hand"
        tpl.save(update_fields=["subject"])

        call_command("seed_platform_comms")

        tpl.refresh_from_db()
        self.assertEqual(tpl.subject, "Edited by hand")

    def test_dry_run_writes_nothing(self):
        call_command("seed_platform_comms", "--dry-run")

        self.assertFalse(
            MessageTemplate.base_objects.filter(tenant=self.platform).exists()
        )

    def test_fails_clearly_when_platform_tenant_missing(self):
        Tenant.objects.filter(is_platform=True).delete()

        with self.assertRaises(CommandError) as ctx:
            call_command("seed_platform_comms")

        self.assertIn("ensure_platform_tenant", str(ctx.exception))

    def test_seeds_onto_the_platform_tenant_only(self):
        """A studio must not receive ANJASI's own templates."""
        studio = Tenant.objects.create(name="Setu Yoga", subdomain="setu-yoga")

        call_command("seed_platform_comms")

        self.assertFalse(
            MessageTemplate.base_objects.filter(tenant=studio).exists()
        )


class SeededTemplateConstraintTests(TestCase):
    """Constraints that would otherwise surface only when a real send fails."""

    def setUp(self):
        self.platform = Tenant.objects.create(
            name="ANJASI", subdomain="anjasi", is_platform=True
        )
        call_command("seed_platform_comms")

    def test_every_template_has_a_subject(self):
        """adapters/email.py refuses to send an email with an empty subject.

        Without this test a subject-less template would seed cleanly and then
        fail at send time, which is exactly the kind of gap that is expensive
        to find in production.
        """
        blank = [
            t.name
            for t in MessageTemplate.base_objects.filter(tenant=self.platform)
            if not (t.subject or "").strip()
        ]
        self.assertEqual(blank, [], f"templates with no subject: {blank}")

    def test_every_template_is_email(self):
        """SMS and WhatsApp credentials are tenant-owned, so ANJASI cannot
        send on those channels without borrowing a studio's DLT header."""
        channels = {
            t.channel
            for t in MessageTemplate.base_objects.filter(tenant=self.platform)
        }
        self.assertEqual(channels, {Channel.EMAIL})

    def test_every_template_documents_a_recipient_field(self):
        """_resolve_recipient() reads context['email'] for the EMAIL channel;
        a template that does not document it invites a payload without one."""
        for t in MessageTemplate.base_objects.filter(tenant=self.platform):
            with self.subTest(template=t.name):
                self.assertIn("email", t.variables)

    def test_event_names_match_the_platform_comms_constants(self):
        """A typo'd event name matches no rule and sends nothing, silently."""
        seeded = set(
            TriggerRule.base_objects.filter(tenant=self.platform)
            .values_list("event_name", flat=True)
        )
        expected = {
            platform_comms.TENANT_INVITED,
            platform_comms.TENANT_ACTIVATED,
            platform_comms.SUBSCRIPTION_INVOICE,
            platform_comms.SUBSCRIPTION_PAYMENT_FAILED,
            platform_comms.SERVICE_NOTICE,
        }
        self.assertEqual(seeded, expected)


class NotifyPlatformAfterSeedingTests(TestCase):
    """The whole point: notify_platform() should now actually dispatch."""

    def setUp(self):
        Tenant.objects.create(name="ANJASI", subdomain="anjasi", is_platform=True)

    def test_every_platform_event_dispatches_once_seeded(self):
        call_command("seed_platform_comms")

        for event in [
            platform_comms.TENANT_INVITED,
            platform_comms.TENANT_ACTIVATED,
            platform_comms.SUBSCRIPTION_INVOICE,
            platform_comms.SUBSCRIPTION_PAYMENT_FAILED,
            platform_comms.SERVICE_NOTICE,
        ]:
            with self.subTest(event=event):
                with patch(
                    "apps.communications.services.communication_service.handle_event"
                ) as handle_event:
                    sent = platform_comms.notify_platform(
                        event, {"email": "owner@studio.com", "owner_name": "Asha"}
                    )
                self.assertTrue(sent, f"{event} did not dispatch")
                handle_event.assert_called_once()

    def test_events_still_report_failure_before_seeding(self):
        """Guards the regression the seeding is meant to fix."""
        with self.assertLogs("apps.communications.platform", level="ERROR"):
            sent = platform_comms.notify_platform(
                platform_comms.TENANT_INVITED, {"email": "owner@studio.com"}
            )
        self.assertFalse(sent)
