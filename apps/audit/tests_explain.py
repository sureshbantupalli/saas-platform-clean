"""
Tests for Phase 7.2 explainability layer.

Covers: output structure, log composition, N+1 guards,
        determinism, build_summary, tenant isolation.
"""
from decimal import Decimal

from django.test import TestCase

from apps.audit.explain_service import (
    build_summary,
    explain_member,
    explain_nudge,
    explain_payment,
)
from apps.audit.models import SettingsAuditLog
from apps.core.models import Branch, Tenant
from apps.payments.models import Payment, PaymentStatus
from apps.revenue.models import MemberRevenueSignal, RiskLevel


# ── Fixtures ──────────────────────────────────────────────────────────────────

_ctr = [0]
def _uid():
    _ctr[0] += 1
    return _ctr[0]


def _make_tenant():
    n = _uid()
    return Tenant.objects.create(name=f"ExplainGym{n}", subdomain=f"explaingym{n}")


def _make_member(tenant):
    from apps.accounts.models import User
    from apps.authority.models import Role
    from members.models import Member
    role = Role.base_objects.create(tenant=tenant, name=f"Role{_uid()}")
    user = User.objects.create_user(
        email=f"u{_uid()}@explain.com", password="x",
        tenant=tenant, role=role,
    )
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name="Test", last_name="Member",
        email=f"m{_uid()}@explain.com",
    )


def _make_payment(tenant):
    return Payment.objects.create(
        tenant=tenant,
        amount=Decimal("500"),
        purpose="membership",
        status=PaymentStatus.CREATED,
    )


def _log(tenant, *, module="payments", action="update", source="system", metadata=None, **kwargs):
    return SettingsAuditLog.objects.create(
        tenant=tenant, module=module, action=action, source=source,
        metadata=metadata or {}, **kwargs,
    )


# ── explain_member ────────────────────────────────────────────────────────────

class ExplainMemberStructureTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()
        self.member = _make_member(self.tenant)

    def test_explain_member_structure(self):
        result = explain_member(self.member, tenant=self.tenant)
        self.assertIn("member_id",       result)
        self.assertIn("risk_level",      result)
        self.assertIn("risk_reason",     result)
        self.assertIn("recent_activity", result)
        self.assertIn("summary",         result)

    def test_member_id_is_string(self):
        result = explain_member(self.member, tenant=self.tenant)
        self.assertIsInstance(result["member_id"], str)
        self.assertEqual(result["member_id"], str(self.member.id))

    def test_no_signal_returns_unknown_risk(self):
        result = explain_member(self.member, tenant=self.tenant)
        self.assertEqual(result["risk_level"], "unknown")
        self.assertIsNone(result["risk_reason"])

    def test_signal_populates_risk_fields(self):
        MemberRevenueSignal.objects.create(
            member=self.member,
            risk_level=RiskLevel.HIGH,
            risk_reason="missed_2_payments",
        )
        result = explain_member(self.member, tenant=self.tenant)
        self.assertEqual(result["risk_level"],  "high")
        self.assertEqual(result["risk_reason"], "missed_2_payments")


class ExplainMemberLogsTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()
        self.member = _make_member(self.tenant)

    def test_explain_uses_logs(self):
        _log(self.tenant, metadata={"member_id": str(self.member.id)},
             field_name="status", new_value="active")
        result = explain_member(self.member, tenant=self.tenant)
        self.assertEqual(len(result["recent_activity"]), 1)
        entry = result["recent_activity"][0]
        self.assertEqual(entry["field"], "status")
        self.assertEqual(entry["to"],    "active")

    def test_activity_entry_has_required_keys(self):
        _log(self.tenant, metadata={"member_id": str(self.member.id)})
        entry = explain_member(self.member, tenant=self.tenant)["recent_activity"][0]
        for key in ("when", "what", "field", "from", "to", "source"):
            self.assertIn(key, entry)

    def test_no_logs_returns_empty_activity(self):
        result = explain_member(self.member, tenant=self.tenant)
        self.assertEqual(result["recent_activity"], [])

    def test_long_values_are_truncated_to_100(self):
        long = "x" * 200
        _log(self.tenant, metadata={"member_id": str(self.member.id)},
             field_name="status", old_value=long, new_value=long)
        entry = explain_member(self.member, tenant=self.tenant)["recent_activity"][0]
        self.assertEqual(len(entry["from"]), 100)
        self.assertEqual(len(entry["to"]),   100)

    def test_none_values_stay_none(self):
        _log(self.tenant, metadata={"member_id": str(self.member.id)},
             old_value=None, new_value=None)
        entry = explain_member(self.member, tenant=self.tenant)["recent_activity"][0]
        self.assertIsNone(entry["from"])
        self.assertIsNone(entry["to"])

    def test_explain_member_query_count(self):
        """Exactly 2 queries: one for logs, one for revenue signal."""
        _log(self.tenant, metadata={"member_id": str(self.member.id)})
        with self.assertNumQueries(2):
            explain_member(self.member, tenant=self.tenant)

    def test_explain_is_stable(self):
        """Same inputs must produce identical output."""
        _log(self.tenant, metadata={"member_id": str(self.member.id)},
             field_name="status", new_value="active")
        r1 = explain_member(self.member, tenant=self.tenant)
        r2 = explain_member(self.member, tenant=self.tenant)
        self.assertEqual(r1["member_id"],       r2["member_id"])
        self.assertEqual(r1["risk_level"],      r2["risk_level"])
        self.assertEqual(len(r1["recent_activity"]), len(r2["recent_activity"]))
        self.assertEqual(r1["summary"],         r2["summary"])

    def test_tenant_isolation(self):
        """Logs from another tenant must not appear."""
        other_tenant = _make_tenant()
        other_member = _make_member(other_tenant)
        _log(other_tenant, metadata={"member_id": str(other_member.id)})
        result = explain_member(self.member, tenant=self.tenant)
        self.assertEqual(result["recent_activity"], [])


# ── explain_payment ───────────────────────────────────────────────────────────

class ExplainPaymentTests(TestCase):

    def setUp(self):
        self.tenant  = _make_tenant()
        self.payment = _make_payment(self.tenant)

    def test_explain_payment_structure(self):
        result = explain_payment(self.payment, tenant=self.tenant)
        self.assertIn("payment_id",      result)
        self.assertIn("status",          result)
        self.assertIn("recent_activity", result)

    def test_payment_status_reflects_model(self):
        result = explain_payment(self.payment, tenant=self.tenant)
        self.assertEqual(result["status"], PaymentStatus.CREATED)

    def test_payment_logs_filtered(self):
        _log(self.tenant, metadata={"payment_id": str(self.payment.id)},
             field_name="status", new_value="SUCCESS")
        _log(self.tenant, metadata={"payment_id": "other-id"})
        result = explain_payment(self.payment, tenant=self.tenant)
        self.assertEqual(len(result["recent_activity"]), 1)

    def test_explain_payment_query_count(self):
        """Exactly 1 query: logs only (payment.status is already loaded)."""
        with self.assertNumQueries(1):
            explain_payment(self.payment, tenant=self.tenant)


# ── explain_nudge ─────────────────────────────────────────────────────────────

class ExplainNudgeTests(TestCase):

    def setUp(self):
        self.tenant = _make_tenant()
        self.member = _make_member(self.tenant)

    def test_explain_nudge_structure(self):
        result = explain_nudge(self.member, tenant=self.tenant)
        self.assertIn("member_id",    result)
        self.assertIn("nudge_events", result)

    def test_nudge_filters_whatsapp_module(self):
        _log(self.tenant, module="whatsapp",
             metadata={"member_id": str(self.member.id)})
        _log(self.tenant, module="payments",
             metadata={"member_id": str(self.member.id)})
        result = explain_nudge(self.member, tenant=self.tenant)
        self.assertEqual(len(result["nudge_events"]), 1)
        self.assertEqual(result["nudge_events"][0]["what"], "whatsapp.update")

    def test_explain_nudge_query_count(self):
        """Exactly 1 query."""
        with self.assertNumQueries(1):
            explain_nudge(self.member, tenant=self.tenant)


# ── build_summary ─────────────────────────────────────────────────────────────

class BuildSummaryTests(TestCase):

    def _explanation(self, risk_level=None, risk_reason=None):
        return {"risk_level": risk_level, "risk_reason": risk_reason}

    def test_high_risk_with_reason(self):
        summary = build_summary(self._explanation("high", "missed_2_payments"))
        self.assertIn("high risk", summary.lower())
        self.assertIn("two consecutive payments", summary.lower())

    def test_medium_risk(self):
        summary = build_summary(self._explanation("medium", "missed_1"))
        self.assertIn("early risk", summary.lower())

    def test_low_risk(self):
        summary = build_summary(self._explanation("low"))
        self.assertIn("no immediate risk", summary.lower())

    def test_no_signal(self):
        summary = build_summary(self._explanation())
        self.assertIsInstance(summary, str)
        self.assertTrue(len(summary) > 0)

    def test_unknown_reason_omits_reason_text(self):
        summary = build_summary(self._explanation("high", "unknown_future_reason"))
        self.assertIn("high risk", summary.lower())
        self.assertNotIn("unknown_future_reason", summary)
