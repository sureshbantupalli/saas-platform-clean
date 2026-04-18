"""
Tenant-specific payment config tests.

Covers:
  - EncryptedCharField round-trip (encrypt on write, decrypt on read)
  - TenantPaymentConfig model (uniqueness, is_active flag)
  - get_active_payment_config(): found, not found, global fallback
  - RazorpayAdapter(config) — uses config credentials, not global settings
  - API create_payment with razorpay: uses tenant config, rejects missing config
  - Webhook: resolves webhook_secret from tenant config
  - Settings UI: GET renders, POST saves, blank secrets kept, is_active toggled
"""
import hashlib
import hmac
import json
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Tenant, Branch
from members.models import Member
from apps.memberships.models import Membership, MembershipPlan
from apps.payments.models import Payment, PaymentGateway, PaymentStatus, TenantPaymentConfig
from apps.payments.gateways.razorpay_adapter import RazorpayAdapter, RazorpayError
from apps.payments.services.config_service import get_active_payment_config, PaymentConfigError
from apps.payments.services.payment_service import PaymentService
from apps.payments.utils.encryption import encrypt_value, decrypt_value


# ── Shared test encryption key (valid Fernet key) ─────────────────────────────

TEST_ENC_KEY = "BywK4uUFhAvnBYlTJi85zxFGzl74PSoGcVcbKPs_9bY="

ENC_SETTINGS = {"PAYMENTS_ENCRYPTION_KEY": TEST_ENC_KEY}

# No-placeholder Razorpay settings to test global fallback
REAL_RZP_SETTINGS = {
    "RAZORPAY_KEY_ID":         "rzp_test_real_key",
    "RAZORPAY_KEY_SECRET":     "real_secret",
    "RAZORPAY_WEBHOOK_SECRET": "real_wh_secret",
    **ENC_SETTINGS,
}

# Placeholder settings (fallback should NOT trigger)
PLACEHOLDER_RZP_SETTINGS = {
    "RAZORPAY_KEY_ID":         "rzp_test_placeholder",
    "RAZORPAY_KEY_SECRET":     "placeholder_secret",
    "RAZORPAY_WEBHOOK_SECRET": "webhook_placeholder",
    **ENC_SETTINGS,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_world(name="ConfigGym", email="cfg@test.com"):
    tenant = Tenant.objects.create(name=name, subdomain=name.lower().replace(" ", "-"))
    branch = Branch.objects.create(tenant=tenant, name="Main", is_active=True)
    role   = Role.objects.create(tenant=tenant, name="Admin")
    user   = User.objects.create_user(email=email, password="pass123", tenant=tenant, role=role)
    member = Member.objects.create(tenant=tenant, created_by=user, first_name="T", last_name="T", email="t@t.com")
    member.branches.add(branch)
    plan = MembershipPlan.objects.create(
        tenant=tenant, branch=branch, name="Monthly",
        plan_type="DURATION", price=Decimal("1000"),
        billing_cycle_type="MONTHLY", billing_interval=1,
    )
    membership = Membership.base_objects.create(
        tenant=tenant, member=member, branch=branch, plan=plan,
        plan_name=plan.name, start_date=date.today(), end_date=date.today(),
        status="pending", payment_status="unpaid",
        amount_paid=Decimal("0"), fee_amount=Decimal("1000"), created_by=user,
    )
    return tenant, branch, user, member, plan, membership


def make_config(tenant, key_id="rzp_test_k", key_secret="sec", webhook_secret="wh", active=True):
    return TenantPaymentConfig.objects.create(
        tenant=tenant, provider="razorpay",
        key_id=key_id, key_secret=key_secret,
        webhook_secret=webhook_secret, is_active=active,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Encryption utility
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**ENC_SETTINGS)
class EncryptionUtilTests(TestCase):

    def test_encrypt_then_decrypt_returns_original(self):
        secret = "my_super_secret_key"
        self.assertEqual(decrypt_value(encrypt_value(secret)), secret)

    def test_encrypt_empty_returns_empty(self):
        self.assertEqual(encrypt_value(""), "")

    def test_decrypt_empty_returns_empty(self):
        self.assertEqual(decrypt_value(""), "")

    def test_encrypted_value_differs_from_plaintext(self):
        plaintext = "secret123"
        self.assertNotEqual(encrypt_value(plaintext), plaintext)

    def test_decrypt_invalid_token_raises(self):
        with self.assertRaises(ValueError):
            decrypt_value("not_a_fernet_token")


# ══════════════════════════════════════════════════════════════════════════════
# 2. TenantPaymentConfig model
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**ENC_SETTINGS)
class TenantPaymentConfigModelTests(TestCase):

    def setUp(self):
        self.tenant, *_ = make_world("ModelGym", "model@test.com")

    def test_secrets_stored_encrypted_in_db(self):
        cfg = make_config(self.tenant, key_secret="plaintext_secret")
        # .values() still calls from_db_value; use raw SQL to read the actual stored bytes
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT key_secret FROM tenant_payment_configs WHERE id = %s", [str(cfg.pk)])
            raw = cur.fetchone()[0]
        self.assertNotEqual(raw, "plaintext_secret")
        self.assertTrue(raw.startswith("gAAAAA"), f"Expected Fernet token, got: {raw[:20]}")

    def test_secrets_decrypted_on_read(self):
        cfg = make_config(self.tenant, key_secret="my_key_secret", webhook_secret="my_wh")
        cfg.refresh_from_db()
        self.assertEqual(cfg.key_secret,     "my_key_secret")
        self.assertEqual(cfg.webhook_secret, "my_wh")

    def test_key_id_not_encrypted(self):
        cfg = make_config(self.tenant, key_id="rzp_test_ABCDE")
        cfg.refresh_from_db()
        self.assertEqual(cfg.key_id, "rzp_test_ABCDE")

    def test_unique_together_prevents_duplicate_provider(self):
        from django.db import IntegrityError
        make_config(self.tenant)
        with self.assertRaises(IntegrityError):
            TenantPaymentConfig.objects.create(
                tenant=self.tenant, provider="razorpay",
                key_id="other", key_secret="other", webhook_secret="other",
            )

    def test_different_tenants_can_have_same_provider(self):
        t2, *_ = make_world("OtherGym", "other@test.com")
        cfg1 = make_config(self.tenant)
        cfg2 = make_config(t2)
        self.assertNotEqual(cfg1.pk, cfg2.pk)

    def test_str_includes_tenant_and_status(self):
        cfg = make_config(self.tenant, active=True)
        self.assertIn("active", str(cfg))
        cfg.is_active = False
        cfg.save()
        self.assertIn("inactive", str(cfg))


# ══════════════════════════════════════════════════════════════════════════════
# 3. get_active_payment_config
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**ENC_SETTINGS)
class GetActivePaymentConfigTests(TestCase):

    def setUp(self):
        self.tenant, *_ = make_world("CfgSvcGym", "cfgsvc@test.com")

    def test_returns_tenant_config_when_active(self):
        cfg = make_config(self.tenant, key_id="rzp_test_FOUND", active=True)
        result = get_active_payment_config(self.tenant, "razorpay")
        self.assertEqual(result.key_id, "rzp_test_FOUND")

    def test_ignores_inactive_config(self):
        make_config(self.tenant, key_id="rzp_test_INACTIVE", active=False)
        with override_settings(**PLACEHOLDER_RZP_SETTINGS):
            with self.assertRaises(PaymentConfigError):
                get_active_payment_config(self.tenant, "razorpay")

    @override_settings(**REAL_RZP_SETTINGS)
    def test_falls_back_to_global_settings_when_no_tenant_config(self):
        result = get_active_payment_config(self.tenant, "razorpay")
        self.assertEqual(result.key_id,         "rzp_test_real_key")
        self.assertEqual(result.key_secret,     "real_secret")
        self.assertEqual(result.webhook_secret, "real_wh_secret")

    @override_settings(**PLACEHOLDER_RZP_SETTINGS)
    def test_raises_when_no_config_and_placeholder_settings(self):
        with self.assertRaises(PaymentConfigError):
            get_active_payment_config(self.tenant, "razorpay")

    def test_tenant_config_takes_priority_over_global_settings(self):
        make_config(self.tenant, key_id="rzp_test_TENANT", active=True)
        with override_settings(**REAL_RZP_SETTINGS):
            result = get_active_payment_config(self.tenant, "razorpay")
        self.assertEqual(result.key_id, "rzp_test_TENANT")


# ══════════════════════════════════════════════════════════════════════════════
# 4. RazorpayAdapter with tenant config
# ══════════════════════════════════════════════════════════════════════════════

class RazorpayAdapterWithConfigTests(TestCase):

    def _stub_payment(self, amount=Decimal("1000")):
        s = MagicMock()
        s.id             = uuid.uuid4()
        s.amount         = amount
        s.currency       = "INR"
        s.reference_type = "membership"
        s.reference_id   = uuid.uuid4()
        return s

    def _config(self, key_id="rzp_test_CFG", key_secret="cfg_secret"):
        return SimpleNamespace(key_id=key_id, key_secret=key_secret, webhook_secret="wh_sec")

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_adapter_uses_config_credentials(self, MockClient):
        MockClient.return_value.order.create.return_value = {"id": "order_X", "currency": "INR"}
        config = self._config(key_id="rzp_test_MY_KEY", key_secret="my_secret")
        RazorpayAdapter(config).create_order(self._stub_payment())
        MockClient.assert_called_once_with(auth=("rzp_test_MY_KEY", "my_secret"))

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_adapter_returns_config_key_id_as_public_key(self, MockClient):
        MockClient.return_value.order.create.return_value = {"id": "order_Y", "currency": "INR"}
        config = self._config(key_id="rzp_test_PUBLIC")
        result = RazorpayAdapter(config).create_order(self._stub_payment())
        self.assertEqual(result["key"], "rzp_test_PUBLIC")

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_amount_converted_to_paise(self, MockClient):
        MockClient.return_value.order.create.return_value = {"id": "o", "currency": "INR"}
        RazorpayAdapter(self._config()).create_order(self._stub_payment(Decimal("2500")))
        args = MockClient.return_value.order.create.call_args[0][0]
        self.assertEqual(args["amount"], 250000)


# ══════════════════════════════════════════════════════════════════════════════
# 5. API create_payment — tenant config wired
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**ENC_SETTINGS)
class CreatePaymentTenantConfigAPITests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user, self.member, self.plan, self.membership = \
            make_world("APIGym", "api@test.com")
        self.client = Client()
        self.client.login(username="api@test.com", password="pass123")
        self.url = reverse("api_payment_create")

    def _post(self, data):
        return self.client.post(self.url, data=json.dumps(data), content_type="application/json")

    def _base_payload(self, amount="1000"):
        return {
            "amount":         amount,
            "currency":       "INR",
            "purpose":        "membership",
            "reference_type": "membership",
            "reference_id":   str(self.membership.pk),
            "gateway":        "razorpay",
        }

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_uses_tenant_config_key_id_in_response(self, MockAdapter):
        make_config(self.tenant, key_id="rzp_test_TENANTKEY", active=True)
        MockAdapter.return_value.create_order.return_value = {
            "order_id": "order_T", "amount": 100000, "currency": "INR",
            "key": "rzp_test_TENANTKEY",
        }
        resp = self._post(self._base_payload())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["key"], "rzp_test_TENANTKEY")

    @override_settings(**PLACEHOLDER_RZP_SETTINGS)
    def test_rejects_when_no_active_config_and_no_real_global_settings(self):
        resp = self._post(self._base_payload())
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No active Razorpay", resp.json()["detail"])

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_inactive_config_causes_rejection(self, MockAdapter):
        make_config(self.tenant, active=False)
        with override_settings(**PLACEHOLDER_RZP_SETTINGS):
            resp = self._post(self._base_payload())
        self.assertEqual(resp.status_code, 400)
        MockAdapter.return_value.create_order.assert_not_called()

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_tenant_config_passed_to_adapter(self, MockAdapter):
        cfg = make_config(self.tenant, key_id="rzp_test_CHECK", active=True)
        MockAdapter.return_value.create_order.return_value = {
            "order_id": "order_C", "amount": 100000, "currency": "INR", "key": "rzp_test_CHECK",
        }
        self._post(self._base_payload())
        # Adapter was constructed — verify config was passed (key_id check)
        init_call_args = MockAdapter.call_args[0]
        self.assertEqual(init_call_args[0].key_id, "rzp_test_CHECK")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Webhook — tenant-specific webhook_secret
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**ENC_SETTINGS)
class WebhookTenantConfigTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user, self.member, self.plan, self.membership = \
            make_world("WHGym", "wh@test.com")
        # Create tenant config with specific webhook_secret
        self.wh_secret = "tenant_specific_webhook_secret"
        make_config(self.tenant, key_id="rzp_test_WH", key_secret="wh_key_sec",
                    webhook_secret=self.wh_secret, active=True)
        # Create a PENDING payment
        self.payment = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal("1000"), purpose="membership",
            reference_type="membership", reference_id=self.membership.pk,
            gateway=PaymentGateway.RAZORPAY, created_by=self.user,
        )
        PaymentService.mark_pending(self.payment, gateway_order_id="order_WHT001")
        self.webhook_url = reverse("api_payment_webhook") + "?gateway=razorpay"

    def _post_webhook(self, body_dict, secret=None):
        secret = secret or self.wh_secret
        raw = json.dumps(body_dict).encode()
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post(
            self.webhook_url, data=raw, content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=sig,
        )

    def _captured_body(self, order_id="order_WHT001", amount_paise=100000):
        return {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {
                "id": "pay_TEST", "order_id": order_id, "amount": amount_paise, "currency": "INR",
            }}},
        }

    def test_webhook_verified_with_tenant_secret(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._post_webhook(self._captured_body())
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)

    def test_webhook_with_wrong_secret_rejected(self):
        resp = self._post_webhook(self._captured_body(), secret="wrong_secret")
        self.assertEqual(resp.status_code, 400)
        self.payment.refresh_from_db()
        self.assertNotEqual(self.payment.status, PaymentStatus.SUCCESS)

    def test_global_settings_secret_rejected_when_tenant_config_exists(self):
        """If tenant has its own config, the global settings secret must NOT work."""
        global_secret = "global_webhook_placeholder"
        with override_settings(RAZORPAY_WEBHOOK_SECRET=global_secret):
            resp = self._post_webhook(self._captured_body(), secret=global_secret)
        # Signature computed with global secret won't match tenant's secret
        self.assertEqual(resp.status_code, 400)

    def test_two_tenants_use_different_secrets(self):
        """Sending Tenant-A's webhook to Tenant-B's payment must fail signature check."""
        tenant2, _, user2, member2, plan2, membership2 = make_world("T2Gym", "t2@test.com")
        make_config(tenant2, key_id="rzp_test_T2", key_secret="t2_sec",
                    webhook_secret="tenant2_secret", active=True)
        payment2 = PaymentService.create_payment(
            tenant=tenant2, amount=Decimal("1000"), purpose="membership",
            reference_type="membership", reference_id=membership2.pk,
            gateway=PaymentGateway.RAZORPAY, created_by=user2,
        )
        PaymentService.mark_pending(payment2, gateway_order_id="order_T2")

        # Sign with tenant1's secret but reference tenant2's order_id
        body = self._captured_body(order_id="order_T2", amount_paise=100000)
        raw  = json.dumps(body).encode()
        sig  = hmac.new(self.wh_secret.encode(), raw, hashlib.sha256).hexdigest()
        resp = self.client.post(
            self.webhook_url, data=raw, content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=sig,
        )
        # tenant2's payment uses tenant2's secret; signing with tenant1's secret fails
        self.assertEqual(resp.status_code, 400)

    def test_webhook_activates_membership_via_signal(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._post_webhook(self._captured_body())
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.payment_status, "paid")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Settings UI view
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**ENC_SETTINGS)
class PaymentSettingsViewTests(TestCase):

    def setUp(self):
        self.tenant, _, self.user, *_ = make_world("UIGym", "ui@test.com")
        self.client = Client()
        self.client.login(username="ui@test.com", password="pass123")
        self.url = reverse("payments:payment_settings")

    def test_get_renders_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Razorpay")

    def test_get_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])

    def test_post_creates_new_config(self):
        resp = self.client.post(self.url, {
            "key_id":         "rzp_test_NEW",
            "key_secret":     "new_key_secret",
            "webhook_secret": "new_wh_secret",
            "is_active":      "on",
        })
        self.assertEqual(resp.status_code, 302)
        cfg = TenantPaymentConfig.objects.get(tenant=self.tenant, provider="razorpay")
        self.assertEqual(cfg.key_id,         "rzp_test_NEW")
        self.assertEqual(cfg.key_secret,     "new_key_secret")
        self.assertEqual(cfg.webhook_secret, "new_wh_secret")
        self.assertTrue(cfg.is_active)

    def test_post_updates_existing_config(self):
        make_config(self.tenant, key_id="rzp_test_OLD", active=False)
        self.client.post(self.url, {
            "key_id":     "rzp_test_UPDATED",
            "key_secret": "updated_sec",
            "is_active":  "on",
        })
        cfg = TenantPaymentConfig.objects.get(tenant=self.tenant, provider="razorpay")
        self.assertEqual(cfg.key_id, "rzp_test_UPDATED")
        self.assertTrue(cfg.is_active)

    def test_blank_key_secret_keeps_existing(self):
        make_config(self.tenant, key_id="rzp_test_K", key_secret="original_secret", active=True)
        self.client.post(self.url, {
            "key_id":     "rzp_test_K",
            "key_secret": "",          # blank → keep existing
            "is_active":  "on",
        })
        cfg = TenantPaymentConfig.objects.get(tenant=self.tenant)
        self.assertEqual(cfg.key_secret, "original_secret")

    def test_blank_webhook_secret_keeps_existing(self):
        make_config(self.tenant, key_id="rzp_test_K", webhook_secret="original_wh", active=True)
        self.client.post(self.url, {
            "key_id":         "rzp_test_K",
            "key_secret":     "any",
            "webhook_secret": "",      # blank → keep existing
            "is_active":      "on",
        })
        cfg = TenantPaymentConfig.objects.get(tenant=self.tenant)
        self.assertEqual(cfg.webhook_secret, "original_wh")

    def test_is_active_false_when_checkbox_unchecked(self):
        make_config(self.tenant, active=True)
        self.client.post(self.url, {
            "key_id":     "rzp_test_K",
            "key_secret": "s",
            # is_active not submitted → False
        })
        cfg = TenantPaymentConfig.objects.get(tenant=self.tenant)
        self.assertFalse(cfg.is_active)

    def test_get_shows_active_status_banner(self):
        make_config(self.tenant, active=True)
        resp = self.client.get(self.url)
        self.assertContains(resp, "active")

    def test_secrets_not_pre_filled_in_form(self):
        make_config(self.tenant, key_secret="supersecret", webhook_secret="wh_secret")
        resp = self.client.get(self.url)
        self.assertNotContains(resp, "supersecret")
        self.assertNotContains(resp, "wh_secret")
