"""Tests for per-tenant SMS / WhatsApp credentials.

The bug this closes is misrouting, not a crash. With credentials in global
environment variables, a second tenant's SMS goes out under the FIRST tenant's
DLT sender header and their WhatsApp under the first tenant's Business
Account. That is a TRAI / Meta compliance violation and it is silent — the
message sends successfully, just as the wrong studio.

So the central test here is `test_each_tenant_sends_under_its_own_credentials`.
The rest guard the properties that make it safe: secrets encrypted at rest,
inactive configs ignored, the constructor never raising, and the env fallback
still working for the single-tenant deployment.
"""

from unittest.mock import Mock, patch

from django.db import connection
from django.test import TestCase

from apps.communications.adapters.sms import SMSAdapter
from apps.communications.adapters.whatsapp import WhatsAppAdapter
from apps.communications.models import MessagingProvider, TenantMessagingConfig
from apps.communications.services.messaging_config_service import (
    get_messaging_config,
)
from apps.core.models import Tenant


def _response(status=200, body=None):
    resp = Mock()
    resp.status_code = status
    resp.text = ""
    resp.json = lambda: (body if body is not None else {"type": "success",
                                                        "messages": [{"id": "x"}]})
    return resp


class PerTenantCredentialTests(TestCase):
    def setUp(self):
        self.studio_a = Tenant.objects.create(name="Setu Yoga", subdomain="setu")
        self.studio_b = Tenant.objects.create(name="FitZone", subdomain="fitzone")

        TenantMessagingConfig.objects.create(
            tenant=self.studio_a, provider=MessagingProvider.MSG91,
            api_key="key-AAA", sender_id="SETUYG", template_id="tpl-A",
            is_active=True,
        )
        TenantMessagingConfig.objects.create(
            tenant=self.studio_b, provider=MessagingProvider.MSG91,
            api_key="key-BBB", sender_id="FITZON", template_id="tpl-B",
            is_active=True,
        )

    def test_each_tenant_sends_under_its_own_credentials(self):
        """THE point of this change.

        Before, both tenants shared whatever was in the environment, so
        FitZone's messages went out under Setu Yoga's DLT header.
        """
        sent = {}
        for name, tenant in [("A", self.studio_a), ("B", self.studio_b)]:
            with patch("requests.post", return_value=_response()) as post:
                SMSAdapter(tenant=tenant).send(
                    to="9876543210", message="hello", text=""
                )
            kwargs = post.call_args.kwargs
            sent[name] = {
                "authkey": kwargs["headers"]["authkey"],
                "sender": kwargs["json"].get("sender"),
                "template": kwargs["json"]["template_id"],
            }

        self.assertEqual(sent["A"]["authkey"], "key-AAA")
        self.assertEqual(sent["A"]["sender"], "SETUYG")
        self.assertEqual(sent["A"]["template"], "tpl-A")

        self.assertEqual(sent["B"]["authkey"], "key-BBB")
        self.assertEqual(sent["B"]["sender"], "FITZON")
        self.assertEqual(sent["B"]["template"], "tpl-B")

        self.assertNotEqual(sent["A"]["sender"], sent["B"]["sender"])

    def test_whatsapp_uses_the_tenants_own_business_account(self):
        TenantMessagingConfig.objects.create(
            tenant=self.studio_a, provider=MessagingProvider.WHATSAPP_CLOUD,
            api_key="tok-AAA", sender_id="111111", template_id="reminder_a",
            template_lang="en_US", is_active=True,
        )
        TenantMessagingConfig.objects.create(
            tenant=self.studio_b, provider=MessagingProvider.WHATSAPP_CLOUD,
            api_key="tok-BBB", sender_id="222222", template_id="reminder_b",
            template_lang="en", is_active=True,
        )

        seen = {}
        for name, tenant in [("A", self.studio_a), ("B", self.studio_b)]:
            with patch("requests.post", return_value=_response()) as post:
                WhatsAppAdapter(tenant=tenant).send(to="9876543210", message="hi")
            seen[name] = {
                "url": post.call_args.args[0],
                "auth": post.call_args.kwargs["headers"]["Authorization"],
                "template": post.call_args.kwargs["json"]["template"]["name"],
                "lang": post.call_args.kwargs["json"]["template"]["language"]["code"],
            }

        self.assertIn("/111111/messages", seen["A"]["url"])
        self.assertIn("/222222/messages", seen["B"]["url"])
        self.assertEqual(seen["A"]["auth"], "Bearer tok-AAA")
        self.assertEqual(seen["B"]["auth"], "Bearer tok-BBB")
        self.assertEqual(seen["A"]["template"], "reminder_a")
        self.assertEqual(seen["B"]["lang"], "en")

    def test_inactive_config_is_ignored(self):
        """A tenant mid-registration must not send under half-set-up credentials."""
        TenantMessagingConfig.objects.filter(tenant=self.studio_a).update(
            is_active=False
        )
        with patch.dict("os.environ", {"MSG91_AUTH_KEY": "", "MSG91_DLT_TE_ID": ""}):
            adapter = SMSAdapter(tenant=self.studio_a)
        self.assertFalse(adapter.is_configured)

    def test_unconfigured_tenant_does_not_borrow_another_tenants_config(self):
        third = Tenant.objects.create(name="Third", subdomain="third")
        with patch.dict("os.environ", {"MSG91_AUTH_KEY": "", "MSG91_DLT_TE_ID": ""}):
            adapter = SMSAdapter(tenant=third)
        self.assertFalse(adapter.is_configured)
        self.assertEqual(adapter.auth_key, "")


class EncryptionTests(TestCase):
    def test_api_key_is_encrypted_at_rest(self):
        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        TenantMessagingConfig.objects.create(
            tenant=tenant, provider=MessagingProvider.MSG91,
            api_key="super-secret-key", template_id="t", is_active=True,
        )

        with connection.cursor() as cur:
            cur.execute("SELECT api_key FROM tenant_messaging_configs LIMIT 1")
            raw = cur.fetchone()[0]

        self.assertNotIn("super-secret-key", raw or "")
        self.assertEqual(
            TenantMessagingConfig.objects.first().api_key, "super-secret-key"
        )


class EnvFallbackTests(TestCase):
    """The single-tenant deployment must keep working unchanged."""

    def test_env_used_when_tenant_has_no_config(self):
        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        with patch.dict("os.environ", {"MSG91_AUTH_KEY": "env-key",
                                       "MSG91_DLT_TE_ID": "env-tpl"}):
            adapter = SMSAdapter(tenant=tenant)
        self.assertTrue(adapter.is_configured)
        self.assertEqual(adapter.auth_key, "env-key")

    def test_tenant_config_wins_over_env(self):
        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        TenantMessagingConfig.objects.create(
            tenant=tenant, provider=MessagingProvider.MSG91,
            api_key="db-key", template_id="db-tpl", is_active=True,
        )
        with patch.dict("os.environ", {"MSG91_AUTH_KEY": "env-key",
                                       "MSG91_DLT_TE_ID": "env-tpl"}):
            adapter = SMSAdapter(tenant=tenant)
        self.assertEqual(adapter.auth_key, "db-key")

    def test_env_fallback_is_logged_loudly_with_multiple_tenants(self):
        """Silent misrouting is the failure mode; make it findable."""
        Tenant.objects.create(name="Setu", subdomain="setu")
        second = Tenant.objects.create(name="FitZone", subdomain="fitzone")

        with patch.dict("os.environ", {"MSG91_AUTH_KEY": "env-key",
                                       "MSG91_DLT_TE_ID": "env-tpl"}):
            with self.assertLogs("apps.communications.config", level="ERROR") as cap:
                SMSAdapter(tenant=second)

        self.assertIn("GLOBAL env credentials", "\n".join(cap.output))

    def test_no_warning_for_a_single_tenant(self):
        only = Tenant.objects.create(name="Setu", subdomain="setu")
        with patch.dict("os.environ", {"MSG91_AUTH_KEY": "env-key",
                                       "MSG91_DLT_TE_ID": "env-tpl"}):
            with patch("apps.communications.services."
                       "messaging_config_service.logger") as log:
                SMSAdapter(tenant=only)
        log.error.assert_not_called()


class ConstructorSafetyTests(TestCase):
    """_get_adapter() builds every adapter on every send, so none may raise."""

    def test_constructors_never_raise(self):
        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        SMSAdapter(tenant=tenant)
        WhatsAppAdapter(tenant=tenant)
        SMSAdapter(tenant=None)
        WhatsAppAdapter(tenant=None)

    def test_a_broken_config_lookup_does_not_break_sending(self):
        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        with patch(
            "apps.communications.models.TenantMessagingConfig.objects.filter",
            side_effect=RuntimeError("db exploded"),
        ):
            adapter = SMSAdapter(tenant=tenant)   # must not raise
        self.assertIsNotNone(adapter)


class ServiceWiringTests(TestCase):
    def test_get_adapter_passes_the_tenant_through(self):
        from apps.communications.services.communication_service import _get_adapter
        from apps.communications.models import Channel

        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        TenantMessagingConfig.objects.create(
            tenant=tenant, provider=MessagingProvider.MSG91,
            api_key="wired-key", template_id="wired-tpl", is_active=True,
        )

        adapter = _get_adapter(Channel.SMS, tenant)
        self.assertEqual(adapter.auth_key, "wired-key")

    def test_email_adapter_is_not_tenant_scoped(self):
        """SES is ANJASI-owned infrastructure — deliberately global."""
        from apps.communications.services.communication_service import _get_adapter
        from apps.communications.models import Channel

        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        adapter = _get_adapter(Channel.EMAIL, tenant)
        self.assertFalse(hasattr(adapter, "tenant"))


class ConfigServiceTests(TestCase):
    def test_returns_none_when_nothing_configured(self):
        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        with patch.dict("os.environ", {"MSG91_AUTH_KEY": "", "MSG91_DLT_TE_ID": "",
                                       "WHATSAPP_ACCESS_TOKEN": "",
                                       "WHATSAPP_PHONE_NUMBER_ID": ""}):
            self.assertIsNone(
                get_messaging_config(tenant, MessagingProvider.MSG91)
            )
            self.assertIsNone(
                get_messaging_config(tenant, MessagingProvider.WHATSAPP_CLOUD)
            )

    def test_providers_are_isolated(self):
        """An MSG91 row must not satisfy a WhatsApp lookup."""
        tenant = Tenant.objects.create(name="Setu", subdomain="setu")
        TenantMessagingConfig.objects.create(
            tenant=tenant, provider=MessagingProvider.MSG91,
            api_key="sms-key", template_id="t", is_active=True,
        )
        with patch.dict("os.environ", {"WHATSAPP_ACCESS_TOKEN": "",
                                       "WHATSAPP_PHONE_NUMBER_ID": ""}):
            self.assertIsNone(
                get_messaging_config(tenant, MessagingProvider.WHATSAPP_CLOUD)
            )
