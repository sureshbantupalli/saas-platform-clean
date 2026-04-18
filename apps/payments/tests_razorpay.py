"""
Razorpay integration tests.

Covers:
  - RazorpayAdapter unit (mocked SDK)
  - API create_payment with gateway=razorpay
  - Webhook: captured, failed, invalid signature, wrong secret,
    idempotency, unknown order, amount mismatch
  - End-to-end: partial cash + Razorpay remainder → membership active
  - Edge: zero-balance overpayment blocked
"""
import hashlib
import hmac
import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Tenant, Branch
from members.models import Member
from apps.memberships.models import Membership, MembershipPlan
from apps.payments.gateways.razorpay_adapter import RazorpayAdapter, RazorpayError
from apps.payments.models import Payment, PaymentEvent, PaymentGateway, PaymentStatus
from apps.payments.services.payment_service import PaymentService, PaymentError


# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_KEY_ID      = "rzp_test_key"
FAKE_KEY_SECRET  = "rzp_secret"
FAKE_SECRET      = "test_webhook_secret"

RZP_SETTINGS = {
    "RAZORPAY_KEY_ID":         FAKE_KEY_ID,
    "RAZORPAY_KEY_SECRET":     FAKE_KEY_SECRET,
    "RAZORPAY_WEBHOOK_SECRET": FAKE_SECRET,
}


# ── Shared fixtures ───────────────────────────────────────────────────────────

def make_rzp_world(gym_name="RZPGym", email="rzp@test.com"):
    tenant = Tenant.objects.create(name=gym_name, subdomain=gym_name.lower())
    branch = Branch.objects.create(tenant=tenant, name="Main", is_active=True)
    role   = Role.objects.create(tenant=tenant, name="Admin")
    user   = User.objects.create_user(email=email, password="pass123", tenant=tenant, role=role)
    member = Member.objects.create(tenant=tenant, created_by=user, first_name="R", last_name="P", email="r@p.com")
    member.branches.add(branch)
    plan = MembershipPlan.objects.create(
        tenant=tenant, branch=branch, name="Quarterly",
        plan_type="DURATION", price=Decimal("2500"),
        billing_cycle_type="MONTHLY", billing_interval=3,
    )
    membership = Membership.base_objects.create(
        tenant=tenant, member=member, branch=branch, plan=plan,
        plan_name=plan.name, start_date=date.today(), end_date=date.today(),
        status="pending", payment_status="unpaid", amount_paid=Decimal("0"),
        fee_amount=Decimal("2500"), created_by=user,
    )
    return tenant, branch, user, member, plan, membership


def _webhook_body(event, order_id, payment_id, amount_paise):
    return {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id":       payment_id,
                    "order_id": order_id,
                    "amount":   amount_paise,
                    "currency": "INR",
                },
            },
        },
    }


def _sign(raw: bytes, secret: str = FAKE_SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _post_webhook(client, body_dict, secret=FAKE_SECRET, gateway="razorpay"):
    raw = json.dumps(body_dict).encode()
    sig = _sign(raw, secret)
    url = reverse("api_payment_webhook") + f"?gateway={gateway}"
    return client.post(url, data=raw, content_type="application/json",
                       HTTP_X_RAZORPAY_SIGNATURE=sig)


# ══════════════════════════════════════════════════════════════════════════════
# 1. RazorpayAdapter Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**RZP_SETTINGS)
class RazorpayAdapterTests(TestCase):

    def setUp(self):
        from types import SimpleNamespace
        self._cfg = SimpleNamespace(key_id=FAKE_KEY_ID, key_secret="fake_secret")

    def _stub(self, amount=Decimal("1500"), currency="INR"):
        s = MagicMock()
        s.id             = uuid.uuid4()
        s.amount         = amount
        s.currency       = currency
        s.reference_type = "membership"
        s.reference_id   = uuid.uuid4()
        return s

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_create_order_returns_correct_shape(self, MockClient):
        MockClient.return_value.order.create.return_value = {
            "id": "order_ABC", "currency": "INR"
        }
        result = RazorpayAdapter(self._cfg).create_order(self._stub(Decimal("1500")))

        self.assertEqual(result["order_id"], "order_ABC")
        self.assertEqual(result["amount"],   150000)
        self.assertEqual(result["currency"], "INR")
        self.assertEqual(result["key"],      FAKE_KEY_ID)

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_amount_converted_to_paise(self, MockClient):
        MockClient.return_value.order.create.return_value = {"id": "o", "currency": "INR"}
        RazorpayAdapter(self._cfg).create_order(self._stub(Decimal("2500.50")))
        args = MockClient.return_value.order.create.call_args[0][0]
        self.assertEqual(args["amount"], 250050)

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_receipt_and_notes_contain_payment_id(self, MockClient):
        MockClient.return_value.order.create.return_value = {"id": "o", "currency": "INR"}
        stub = self._stub()
        RazorpayAdapter(self._cfg).create_order(stub)
        args = MockClient.return_value.order.create.call_args[0][0]
        self.assertEqual(args["receipt"], str(stub.id))
        self.assertEqual(args["notes"]["payment_id"], str(stub.id))

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_sdk_bad_request_raises_razorpay_error(self, MockClient):
        import razorpay.errors
        MockClient.return_value.order.create.side_effect = razorpay.errors.BadRequestError("bad")
        with self.assertRaises(RazorpayError):
            RazorpayAdapter(self._cfg).create_order(self._stub())

    @patch("apps.payments.gateways.razorpay_adapter.razorpay.Client")
    def test_generic_exception_raises_razorpay_error(self, MockClient):
        MockClient.return_value.order.create.side_effect = Exception("network down")
        with self.assertRaises(RazorpayError):
            RazorpayAdapter(self._cfg).create_order(self._stub())


# ══════════════════════════════════════════════════════════════════════════════
# 2. API: POST /api/payments/create/ with gateway=razorpay
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**RZP_SETTINGS)
class CreatePaymentRazorpayAPITests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user, self.member, self.plan, self.membership = \
            make_rzp_world()
        self.client = Client()
        self.client.login(username="rzp@test.com", password="pass123")

    def _post(self, data):
        return self.client.post(
            reverse("api_payment_create"),
            data=json.dumps(data),
            content_type="application/json",
        )

    def _razorpay_payload(self, amount="2500"):
        return {
            "amount":         amount,
            "currency":       "INR",
            "purpose":        "membership",
            "reference_type": "membership",
            "reference_id":   str(self.membership.pk),
            "gateway":        "razorpay",
        }

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_success_response_contains_order_checkout_data(self, MockAdapter):
        MockAdapter.return_value.create_order.return_value = {
            "order_id": "order_T001", "amount": 250000, "currency": "INR", "key": FAKE_KEY_ID,
        }
        resp = self._post(self._razorpay_payload())
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["order_id"],  "order_T001")
        self.assertEqual(data["amount"],    250000)
        self.assertEqual(data["key"],       FAKE_KEY_ID)
        self.assertIn("payment_id", data)

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_db_payment_created_as_pending_with_gateway_order_id(self, MockAdapter):
        MockAdapter.return_value.create_order.return_value = {
            "order_id": "order_T002", "amount": 250000, "currency": "INR", "key": FAKE_KEY_ID,
        }
        resp = self._post(self._razorpay_payload())
        payment = Payment.base_objects.get(pk=resp.json()["payment_id"])
        self.assertEqual(payment.status,           PaymentStatus.PENDING)
        self.assertEqual(payment.gateway_order_id, "order_T002")
        self.assertEqual(payment.gateway,          PaymentGateway.RAZORPAY)

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_overpayment_blocked_before_sdk_call(self, MockAdapter):
        resp = self._post(self._razorpay_payload(amount="9999"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("balance", resp.json()["detail"].lower())
        MockAdapter.return_value.create_order.assert_not_called()

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_sdk_failure_returns_502(self, MockAdapter):
        MockAdapter.return_value.create_order.side_effect = RazorpayError("timeout")
        resp = self._post(self._razorpay_payload())
        self.assertEqual(resp.status_code, 502)

    def test_cancelled_membership_payment_rejected(self):
        Membership.base_objects.filter(pk=self.membership.pk).update(status="cancelled")
        resp = self._post(self._razorpay_payload(amount="100"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cancelled", resp.json()["detail"])

    @patch("apps.payments.api.views.RazorpayAdapter")
    def test_partial_amount_allowed_within_balance(self, MockAdapter):
        MockAdapter.return_value.create_order.return_value = {
            "order_id": "order_T003", "amount": 100000, "currency": "INR", "key": FAKE_KEY_ID,
        }
        resp = self._post(self._razorpay_payload(amount="1000"))  # 1000 < 2500 balance
        self.assertEqual(resp.status_code, 201)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Webhook Tests
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**RZP_SETTINGS)
class RazorpayWebhookTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user, self.member, self.plan, self.membership = \
            make_rzp_world(gym_name="WebhookGym", email="wh@test.com")
        self.payment = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal("2500"), purpose="membership",
            reference_type="membership", reference_id=self.membership.pk,
            gateway=PaymentGateway.RAZORPAY, created_by=self.user,
        )
        PaymentService.mark_pending(self.payment, gateway_order_id="order_WH001")

    def test_captured_marks_success(self):
        body = _webhook_body("payment.captured", "order_WH001", "pay_OK", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(self.payment.gateway_payment_id, "pay_OK")

    def test_captured_activates_membership(self):
        body = _webhook_body("payment.captured", "order_WH001", "pay_MEM", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            _post_webhook(self.client, body)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.payment_status, "paid")
        self.assertEqual(self.membership.amount_paid, Decimal("2500"))

    def test_failed_event_marks_payment_failed(self):
        body = _webhook_body("payment.failed", "order_WH001", "pay_FAIL", 250000)
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)

    def test_invalid_signature_rejected(self):
        body = _webhook_body("payment.captured", "order_WH001", "pay_X", 250000)
        raw  = json.dumps(body).encode()
        resp = self.client.post(
            reverse("api_payment_webhook") + "?gateway=razorpay",
            data=raw, content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="badsignature",
        )
        self.assertEqual(resp.status_code, 400)
        self.payment.refresh_from_db()
        self.assertNotEqual(self.payment.status, PaymentStatus.SUCCESS)

    def test_wrong_secret_rejected(self):
        body = _webhook_body("payment.captured", "order_WH001", "pay_X", 250000)
        resp = _post_webhook(self.client, body, secret="wrong_secret")
        self.assertEqual(resp.status_code, 400)

    def test_idempotent_duplicate_logs_duplicate_skip(self):
        body = _webhook_body("payment.captured", "order_WH001", "pay_DUP", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            resp1 = _post_webhook(self.client, body)
            resp2 = _post_webhook(self.client, body)
        # Both calls return 200 — duplicate is acknowledged, not rejected
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(
            PaymentEvent.objects.filter(payment=self.payment, event_type="DUPLICATE_SKIP").count(),
            1,
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)

    def test_duplicate_webhook_skipped_without_side_effects(self):
        """A duplicate captured webhook must not re-trigger membership activation."""
        body = _webhook_body("payment.captured", "order_WH001", "pay_DUP2", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            _post_webhook(self.client, body)   # first — activates membership
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        amount_after_first = self.membership.amount_paid

        # Second call — must be a no-op: no second SUCCESS event, no changed amounts
        with self.captureOnCommitCallbacks(execute=True):
            _post_webhook(self.client, body)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.amount_paid, amount_after_first)
        self.assertEqual(
            PaymentEvent.objects.filter(payment=self.payment, event_type="SUCCESS").count(),
            1,
        )

    def test_unknown_order_id_returns_400(self):
        body = _webhook_body("payment.captured", "order_UNKNOWN", "pay_X", 250000)
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        # Original payment must be untouched
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    def test_missing_order_id_rejected(self):
        """Webhook with no order_id must be rejected before touching any payment."""
        body = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id":     "pay_X",
                        "amount": 250000,
                        "currency": "INR",
                        # order_id deliberately omitted
                    },
                },
            },
        }
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("order_id", resp.json()["detail"].lower())
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    def test_amount_mismatch_rejected(self):
        # 100 paise (₹1) vs expected 250000 paise (₹2500)
        body = _webhook_body("payment.captured", "order_WH001", "pay_X", 100)
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("mismatch", resp.json()["detail"].lower())
        self.payment.refresh_from_db()
        # Must be explicitly FAILED — not left in PENDING limbo
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)

    def test_amount_mismatch_logs_event(self):
        """AMOUNT_MISMATCH PaymentEvent is persisted even though we return 400."""
        body = _webhook_body("payment.captured", "order_WH001", "pay_X", 100)
        _post_webhook(self.client, body)
        self.assertTrue(
            PaymentEvent.objects.filter(
                payment=self.payment, event_type="AMOUNT_MISMATCH"
            ).exists()
        )

    def test_zero_amount_mismatch_rejected(self):
        """amount=0 in webhook must not bypass the guard (falsy-check exploit)."""
        body = _webhook_body("payment.captured", "order_WH001", "pay_X", 0)
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("mismatch", resp.json()["detail"].lower())
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)

    def test_currency_mismatch_rejected(self):
        """Wrong currency in webhook must be rejected and payment marked FAILED."""
        body = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id":       "pay_CUR",
                        "order_id": "order_WH001",
                        "amount":   250000,
                        "currency": "USD",
                    },
                },
            },
        }
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("mismatch", resp.json()["detail"].lower())
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)

    def test_every_webhook_call_logs_webhook_event(self):
        body = _webhook_body("payment.captured", "order_WH001", "pay_LOG", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            _post_webhook(self.client, body)
        self.assertTrue(
            PaymentEvent.objects.filter(payment=self.payment, event_type="WEBHOOK").exists()
        )

    def test_unknown_event_type_is_a_noop(self):
        """Unrecognised events should not crash or change payment status."""
        body = _webhook_body("order.paid", "order_WH001", "pay_X", 250000)
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    def test_membership_not_activated_on_amount_mismatch(self):
        """Membership must stay pending when webhook amount does not match."""
        body = _webhook_body("payment.captured", "order_WH001", "pay_X", 100)
        _post_webhook(self.client, body)
        self.membership.refresh_from_db()
        # Amount mismatch → payment FAILED → membership NOT activated
        self.assertNotEqual(self.membership.status, "active")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)

    def test_membership_not_activated_on_invalid_signature(self):
        """Membership must stay pending when webhook signature is invalid."""
        body = _webhook_body("payment.captured", "order_WH001", "pay_X", 250000)
        raw = json.dumps(body).encode()
        resp = self.client.post(
            reverse("api_payment_webhook") + "?gateway=razorpay",
            data=raw, content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="tampered_signature",
        )
        self.assertEqual(resp.status_code, 400)
        self.membership.refresh_from_db()
        self.assertNotEqual(self.membership.status, "active")
        self.payment.refresh_from_db()
        # Payment must be untouched — bad sig = no side effects
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    def test_membership_activated_exactly_once_on_success(self):
        """Membership reaches active state exactly once regardless of webhook retry count."""
        body = _webhook_body("payment.captured", "order_WH001", "pay_ONCE", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            _post_webhook(self.client, body)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.payment_status, "paid")
        first_amount_paid = self.membership.amount_paid

        # Replay the same webhook
        with self.captureOnCommitCallbacks(execute=True):
            resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 200)
        self.membership.refresh_from_db()
        # Amount paid and status must be unchanged after the duplicate
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.amount_paid, first_amount_paid)


# ══════════════════════════════════════════════════════════════════════════════
# 4. End-to-End Flow
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**RZP_SETTINGS)
class RazorpayEndToEndTests(TestCase):
    """
    Full scenario per spec:
      1. Member created
      2. Membership ₹2500 created (pending)
      3. Manual cash ₹1000 → partial
      4. Razorpay order for remaining ₹1500
      5. Webhook fires → membership ACTIVE
    """

    def setUp(self):
        self.tenant, self.branch, self.user, self.member, self.plan, self.membership = \
            make_rzp_world(gym_name="E2EGym", email="e2e@test.com")
        self.client = Client()
        self.client.login(username="e2e@test.com", password="pass123")

    def test_partial_cash_then_razorpay_activates_membership(self):
        # Step 3: Manual partial ₹1000
        p_cash = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal("1000"), purpose="membership",
            reference_type="membership", reference_id=self.membership.pk,
            gateway=PaymentGateway.OFFLINE, payment_method="cash", created_by=self.user,
        )
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(p_cash, payment_method="cash")

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.payment_status, "partial")
        self.assertEqual(self.membership.balance_amount, Decimal("1500"))
        self.assertEqual(self.membership.status, "pending")

        # Step 4: Razorpay order for ₹1500
        with patch("apps.payments.api.views.RazorpayAdapter") as MockAdapter:
            MockAdapter.return_value.create_order.return_value = {
                "order_id": "order_E2E001", "amount": 150000,
                "currency": "INR", "key": FAKE_KEY_ID,
            }
            resp = self.client.post(
                reverse("api_payment_create"),
                data=json.dumps({
                    "amount": "1500", "currency": "INR", "purpose": "membership",
                    "reference_type": "membership",
                    "reference_id":   str(self.membership.pk),
                    "gateway":        "razorpay",
                }),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["order_id"], "order_E2E001")
        self.assertEqual(data["amount"],   150000)

        # Step 5: Webhook fires — payment.captured
        body = _webhook_body("payment.captured", "order_E2E001", "pay_E2E001", 150000)
        raw  = json.dumps(body).encode()
        sig  = _sign(raw)
        with self.captureOnCommitCallbacks(execute=True):
            wh_resp = self.client.post(
                reverse("api_payment_webhook") + "?gateway=razorpay",
                data=raw, content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=sig,
            )
        self.assertEqual(wh_resp.status_code, 200)

        # Membership ACTIVE, fully paid
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status,         "active")
        self.assertEqual(self.membership.payment_status, "paid")
        self.assertEqual(self.membership.amount_paid,    Decimal("2500"))
        self.assertEqual(self.membership.balance_amount, Decimal("0"))

    def test_zero_balance_any_charge_blocked(self):
        """Once membership is fully paid, even ₹1 via Razorpay is blocked."""
        p = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal("2500"), purpose="membership",
            reference_type="membership", reference_id=self.membership.pk,
            gateway=PaymentGateway.OFFLINE, created_by=self.user,
        )
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(p)

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.balance_amount, Decimal("0"))

        resp = self.client.post(
            reverse("api_payment_create"),
            data=json.dumps({
                "amount": "1", "currency": "INR", "purpose": "membership",
                "reference_type": "membership",
                "reference_id":   str(self.membership.pk),
                "gateway":        "razorpay",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_failed_razorpay_payment_then_retry_succeeds(self):
        """Failed payment does not block a fresh Razorpay attempt."""
        # First attempt: Razorpay captures but payment fails
        p_fail = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal("2500"), purpose="membership",
            reference_type="membership", reference_id=self.membership.pk,
            gateway=PaymentGateway.RAZORPAY, created_by=self.user,
        )
        PaymentService.mark_pending(p_fail, gateway_order_id="order_FAIL001")
        PaymentService.mark_payment_failed(p_fail, reason="card declined")

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.payment_status, "unpaid")  # unchanged

        # Second attempt succeeds
        with patch("apps.payments.api.views.RazorpayAdapter") as MockAdapter:
            MockAdapter.return_value.create_order.return_value = {
                "order_id": "order_RETRY001", "amount": 250000,
                "currency": "INR", "key": FAKE_KEY_ID,
            }
            resp = self.client.post(
                reverse("api_payment_create"),
                data=json.dumps({
                    "amount": "2500", "currency": "INR", "purpose": "membership",
                    "reference_type": "membership",
                    "reference_id":   str(self.membership.pk),
                    "gateway":        "razorpay",
                }),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 201)

        body = _webhook_body("payment.captured", "order_RETRY001", "pay_RETRY", 250000)
        raw  = json.dumps(body).encode()
        sig  = _sign(raw)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("api_payment_webhook") + "?gateway=razorpay",
                data=raw, content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE=sig,
            )

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.payment_status, "paid")


# ══════════════════════════════════════════════════════════════════════════════
# 5. Production Hardening Tests
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(**RZP_SETTINGS)
class WebhookProductionHardeningTests(TestCase):
    """
    Covers the three final production-readiness improvements:
    1. order_id scoped to gateway payments only
    2. Structured audit logging for all failure paths
    3. gateway_payment_id validation and conflict detection
    """

    def setUp(self):
        self.tenant, self.branch, self.user, self.member, self.plan, self.membership = \
            make_rzp_world(gym_name="ProdGym", email="prod@test.com")
        self.payment = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal("2500"), purpose="membership",
            reference_type="membership", reference_id=self.membership.pk,
            gateway=PaymentGateway.RAZORPAY, created_by=self.user,
        )
        PaymentService.mark_pending(self.payment, gateway_order_id="order_PROD001")

    # ─── 1. order_id scoping ─────────────────────────────────────────────────

    def test_offline_payment_succeeds_without_gateway_order_id(self):
        """Offline (cash) payments have no gateway_order_id and must work correctly."""
        p = PaymentService.create_payment(
            tenant=self.tenant, amount=Decimal("2500"), purpose="membership",
            reference_type="membership", reference_id=self.membership.pk,
            gateway=PaymentGateway.OFFLINE, payment_method="cash", created_by=self.user,
        )
        # Offline payments are marked success directly — no webhook involved
        self.assertEqual(p.gateway_order_id, "")
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(p, payment_method="cash")
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.SUCCESS)
        self.assertEqual(p.gateway_order_id, "")  # never set for offline

    def test_gateway_payment_missing_order_id_rejected(self):
        """A Razorpay webhook with no order_id is rejected before any DB access."""
        body = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {
                "id": "pay_X", "amount": 250000, "currency": "INR"
                # order_id deliberately absent
            }}},
        }
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("order_id", resp.json()["detail"].lower())
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    def test_gateway_payment_missing_payment_id_rejected(self):
        """A Razorpay webhook with no entity.id is rejected before any DB write."""
        body = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {
                "order_id": "order_PROD001", "amount": 250000, "currency": "INR"
                # entity.id (payment_id) deliberately absent
            }}},
        }
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("payment_id", resp.json()["detail"].lower())
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    # ─── 2. Structured audit logging ─────────────────────────────────────────

    def test_invalid_signature_is_logged_with_structured_data(self):
        """An invalid signature must be logged with reason, gateway, and order_id."""
        body = _webhook_body("payment.captured", "order_PROD001", "pay_X", 250000)
        with self.assertLogs("apps.payments", level="WARNING") as cm:
            resp = _post_webhook(self.client, body, secret="wrong_secret")
        self.assertEqual(resp.status_code, 400)
        record = next(
            r for r in cm.records
            if getattr(r, "reason", None) == "invalid_signature"
        )
        self.assertEqual(record.gateway, "razorpay")
        self.assertEqual(record.order_id, "order_PROD001")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

    def test_amount_mismatch_logs_structured_data(self):
        """Amount mismatch log must contain reason, expected, received, gateway, order_id."""
        body = _webhook_body("payment.captured", "order_PROD001", "pay_X", 100)
        with self.assertLogs("apps.payments", level="WARNING") as cm:
            _post_webhook(self.client, body)
        record = next(
            r for r in cm.records
            if getattr(r, "reason", None) == "amount_mismatch"
        )
        self.assertEqual(record.expected, 250000)   # ₹2500 × 100 paise
        self.assertEqual(record.received, 100)
        self.assertEqual(record.gateway,  "razorpay")
        self.assertEqual(record.order_id, "order_PROD001")

    def test_missing_order_id_is_logged_with_structured_data(self):
        """Missing order_id must be logged with reason and gateway (no DB write occurs)."""
        body = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_X", "amount": 250000}}},
        }
        with self.assertLogs("apps.payments", level="WARNING") as cm:
            _post_webhook(self.client, body)
        record = next(
            r for r in cm.records
            if getattr(r, "reason", None) == "missing_order_id"
        )
        self.assertEqual(record.gateway, "razorpay")

    # ─── 3. gateway_payment_id validation ────────────────────────────────────

    def test_duplicate_gateway_payment_id_is_idempotent(self):
        """Same webhook (same payment_id) replayed after SUCCESS → DUPLICATE_SKIP, no change."""
        body = _webhook_body("payment.captured", "order_PROD001", "pay_SAME", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            resp1 = _post_webhook(self.client, body)
        self.assertEqual(resp1.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(self.payment.gateway_payment_id, "pay_SAME")

        with self.captureOnCommitCallbacks(execute=True):
            resp2 = _post_webhook(self.client, body)
        self.assertEqual(resp2.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(self.payment.gateway_payment_id, "pay_SAME")
        self.assertEqual(
            PaymentEvent.objects.filter(payment=self.payment, event_type="DUPLICATE_SKIP").count(),
            1,
        )

    def test_conflicting_gateway_payment_id_on_pending_rejected(self):
        """A PENDING payment with gateway_payment_id already set rejects a different payment_id."""
        # Simulate a previous partial write that set gateway_payment_id on PENDING
        Payment.base_objects.filter(pk=self.payment.pk).update(gateway_payment_id="pay_FIRST")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)

        body = _webhook_body("payment.captured", "order_PROD001", "pay_CONFLICT", 250000)
        resp = _post_webhook(self.client, body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("conflict", resp.json()["detail"].lower())
        self.payment.refresh_from_db()
        self.assertNotEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertTrue(
            PaymentEvent.objects.filter(payment=self.payment, event_type="PAYMENT_ID_CONFLICT").exists()
        )

    def test_conflicting_gateway_payment_id_on_success_logs_error(self):
        """A webhook for a SUCCESS payment with a different payment_id logs a conflict
        but returns 200 (DUPLICATE_SKIP) to prevent Razorpay from retrying."""
        body = _webhook_body("payment.captured", "order_PROD001", "pay_LEGIT", 250000)
        with self.captureOnCommitCallbacks(execute=True):
            _post_webhook(self.client, body)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.gateway_payment_id, "pay_LEGIT")

        # Replay with a different payment_id (potential replay attack)
        body2 = _webhook_body("payment.captured", "order_PROD001", "pay_EVIL", 250000)
        with self.assertLogs("apps.payments", level="ERROR") as cm:
            resp = _post_webhook(self.client, body2)
        self.assertEqual(resp.status_code, 200)  # acknowledged to stop retries
        record = next(
            r for r in cm.records
            if getattr(r, "reason", None) == "duplicate_or_conflict"
        )
        self.assertEqual(record.expected, "pay_LEGIT")
        self.assertEqual(record.received, "pay_EVIL")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(self.payment.gateway_payment_id, "pay_LEGIT")
