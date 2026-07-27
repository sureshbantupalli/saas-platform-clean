"""Tests for platform-level messaging (ANJASI speaking as itself).

The design models ANJASI as an ordinary tenant flagged ``is_platform=True`` so
the whole communications engine is reused. That buys a lot, but creates two
risks this file pins down:

1. A synthetic tenant gets swept into any job that loops over tenants.
2. Platform messages must never break the operation that triggered them —
   an onboarding email failure must not roll back tenant provisioning.
"""

from unittest.mock import patch

from django.core.management import call_command
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.communications.services import platform_comms
from apps.core.models import Tenant
from apps.core.platform import (
    PlatformTenantMissing,
    exclude_platform,
    get_platform_tenant,
    get_platform_tenant_or_none,
)


class EnsurePlatformTenantCommandTests(TestCase):
    def test_creates_the_platform_tenant(self):
        call_command("ensure_platform_tenant")

        tenant = Tenant.objects.get(is_platform=True)
        self.assertEqual(tenant.subdomain, "anjasi")

    def test_is_idempotent(self):
        """Safe to run on every deploy."""
        call_command("ensure_platform_tenant")
        call_command("ensure_platform_tenant")

        self.assertEqual(Tenant.objects.filter(is_platform=True).count(), 1)

    def test_dry_run_writes_nothing(self):
        call_command("ensure_platform_tenant", "--dry-run")

        self.assertFalse(Tenant.objects.filter(is_platform=True).exists())

    def test_adopts_an_existing_tenant_on_the_same_subdomain(self):
        """A manually provisioned 'anjasi' must not collide on the unique key."""
        Tenant.objects.create(name="Anjasi Internal", subdomain="anjasi")

        call_command("ensure_platform_tenant")

        self.assertEqual(Tenant.objects.filter(subdomain="anjasi").count(), 1)
        self.assertTrue(Tenant.objects.get(subdomain="anjasi").is_platform)


class PlatformTenantResolverTests(TestCase):
    def test_raises_loudly_when_not_provisioned(self):
        """Silently skipping would mean an invoice never sends and nobody knows."""
        with self.assertRaises(PlatformTenantMissing):
            get_platform_tenant()

    def test_or_none_variant_returns_none(self):
        self.assertIsNone(get_platform_tenant_or_none())

    def test_resolves_the_flagged_tenant(self):
        Tenant.objects.create(name="Studio", subdomain="studio")
        platform = Tenant.objects.create(
            name="ANJASI", subdomain="anjasi", is_platform=True
        )

        self.assertEqual(get_platform_tenant(), platform)

    def test_database_rejects_a_second_platform_tenant(self):
        """Two would make the resolver ambiguous and split platform templates."""
        Tenant.objects.create(name="ANJASI", subdomain="anjasi", is_platform=True)

        with self.assertRaises(IntegrityError):
            Tenant.objects.create(
                name="ANJASI Two", subdomain="anjasi-2", is_platform=True
            )


class ExcludePlatformTests(TestCase):
    """Batch jobs loop over tenants; the platform tenant must not be swept in."""

    def setUp(self):
        self.studio = Tenant.objects.create(name="Setu Yoga", subdomain="setu-yoga")
        self.platform = Tenant.objects.create(
            name="ANJASI", subdomain="anjasi", is_platform=True
        )

    def test_drops_only_the_platform_tenant(self):
        result = exclude_platform(Tenant.objects.all())

        self.assertIn(self.studio, result)
        self.assertNotIn(self.platform, result)

    def test_renewal_scheduler_skips_the_platform_tenant(self):
        from apps.renewals import scheduler

        with patch.object(
            scheduler.RenewalTriggerService, "trigger_all", return_value={}
        ) as trigger:
            scheduler.run_daily_renewals()

        scanned = [call.args[0] for call in trigger.call_args_list]
        self.assertIn(self.studio, scanned)
        self.assertNotIn(self.platform, scanned)

    def test_seed_comms_defaults_skips_the_platform_tenant_in_bulk(self):
        call_command("seed_comms_defaults")

        from apps.communications.models import MessageTemplate

        seeded = MessageTemplate.base_objects.filter(tenant=self.platform)
        self.assertFalse(
            seeded.exists(),
            "Studio-shaped defaults must not be seeded into the ANJASI tenant.",
        )

    def test_seed_comms_defaults_still_honours_an_explicit_platform_target(self):
        call_command("seed_comms_defaults", tenant="anjasi")

        from apps.communications.models import MessageTemplate

        self.assertTrue(
            MessageTemplate.base_objects.filter(tenant=self.platform).exists()
        )


class NotifyPlatformTests(TestCase):
    def _configure(self, tenant, event_name):
        """Give the platform tenant a template + rule for `event_name`."""
        from apps.communications.models import Channel, MessageTemplate, TriggerRule

        template = MessageTemplate.objects.create(
            tenant=tenant,
            name=f"Platform: {event_name}",
            channel=Channel.EMAIL,
            subject="Welcome to ANJASI",
            content="Hello {{name}}",
        )
        TriggerRule.objects.create(
            tenant=tenant, event_name=event_name, template=template
        )

    def test_dispatches_under_the_platform_tenant(self):
        platform = Tenant.objects.create(
            name="ANJASI", subdomain="anjasi", is_platform=True
        )
        self._configure(platform, platform_comms.TENANT_INVITED)

        with patch(
            "apps.communications.services.communication_service.handle_event"
        ) as handle_event:
            sent = platform_comms.notify_platform(
                platform_comms.TENANT_INVITED, {"email": "owner@studio.com"}
            )

        self.assertTrue(sent)
        handle_event.assert_called_once()
        self.assertEqual(handle_event.call_args.args[2], platform)

    def test_reports_failure_when_no_trigger_rule_is_configured(self):
        """Silence here would mean an invoice 'succeeds' while sending nothing."""
        Tenant.objects.create(name="ANJASI", subdomain="anjasi", is_platform=True)

        with self.assertLogs("apps.communications.platform", level="ERROR"):
            sent = platform_comms.notify_platform(
                platform_comms.SUBSCRIPTION_INVOICE, {"email": "owner@studio.com"}
            )

        self.assertFalse(sent)

    def test_returns_false_instead_of_raising_when_unprovisioned(self):
        """Provisioning a tenant must not roll back because email is missing."""
        with self.assertLogs("apps.communications.platform", level="ERROR"):
            sent = platform_comms.notify_platform(
                platform_comms.TENANT_INVITED, {"email": "owner@studio.com"}
            )

        self.assertFalse(sent)

    def test_swallows_and_logs_an_unexpected_dispatch_failure(self):
        platform = Tenant.objects.create(
            name="ANJASI", subdomain="anjasi", is_platform=True
        )
        self._configure(platform, platform_comms.SERVICE_NOTICE)

        with patch(
            "apps.communications.services.communication_service.handle_event",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertLogs("apps.communications.platform", level="ERROR"):
                sent = platform_comms.notify_platform(
                    platform_comms.SERVICE_NOTICE, {"email": "owner@studio.com"}
                )

        self.assertFalse(sent)
