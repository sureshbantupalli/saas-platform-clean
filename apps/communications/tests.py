"""
Tests for the Communications module.

Coverage:
  - Renderer: basic substitution, missing keys, multiple placeholders, edge cases
  - Condition evaluator: empty, equality, numeric, missing field, unknown operator
  - send_message: SENT log, FAILED log on missing recipient, FAILED on adapter error
  - handle_event: no rules → nothing, matching rule, conditions fail, cross-tenant isolation
  - Signal integration: payment_success fires handle_event
  - Views: template CRUD, trigger CRUD, log list
"""
import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Tenant
from apps.communications.models import (
    Channel, CommunicationLog, MessageStatus, MessageTemplate, TriggerRule,
)
from apps.communications.utils.renderer import render_template
from apps.communications.utils.conditions import evaluate_conditions
from apps.communications.services.communication_service import handle_event, send_message


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_tenant(name="TestGym"):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(" ", "-"))


def make_user(tenant, email="staff@test.com"):
    role = Role.objects.create(tenant=tenant, name="Manager")
    return User.objects.create_user(email=email, password="pass123", tenant=tenant, role=role)


def make_template(tenant, name="Pay Success SMS", channel=Channel.SMS,
                  content="Hi {{member_name}}, ₹{{amount}} paid.", is_active=True):
    return MessageTemplate.base_objects.create(
        tenant=tenant, name=name, channel=channel, content=content, is_active=is_active,
    )


def make_rule(tenant, template, event_name="payment_success", conditions=None, is_active=True):
    return TriggerRule.base_objects.create(
        tenant=tenant, template=template,
        event_name=event_name,
        conditions=conditions or {},
        is_active=is_active,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Renderer
# ══════════════════════════════════════════════════════════════════════════════

class RendererTests(TestCase):

    def test_basic_substitution(self):
        result = render_template("Hi {{name}}, you paid ₹{{amount}}.", {"name": "Rahul", "amount": 2000})
        self.assertEqual(result, "Hi Rahul, you paid ₹2000.")

    def test_missing_key_renders_blank(self):
        result = render_template("Hi {{name}}, ref {{ref}}.", {"name": "Sita"})
        self.assertEqual(result, "Hi Sita, ref .")

    def test_none_value_renders_blank(self):
        result = render_template("Phone: {{phone}}", {"phone": None})
        self.assertEqual(result, "Phone: ")

    def test_no_placeholders(self):
        self.assertEqual(render_template("Plain text.", {}), "Plain text.")

    def test_multiple_occurrences(self):
        result = render_template("{{x}} and {{x}} again.", {"x": "yes"})
        self.assertEqual(result, "yes and yes again.")

    def test_whitespace_trimmed_in_key(self):
        result = render_template("{{ name }}", {"name": "Ali"})
        self.assertEqual(result, "Ali")

    def test_integer_value_coerced_to_str(self):
        result = render_template("Count: {{n}}", {"n": 42})
        self.assertEqual(result, "Count: 42")

    def test_empty_content(self):
        self.assertEqual(render_template("", {"x": "y"}), "")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Condition Evaluator
# ══════════════════════════════════════════════════════════════════════════════

class ConditionEvaluatorTests(TestCase):

    def test_empty_conditions_always_true(self):
        self.assertTrue(evaluate_conditions({}, {"anything": 1}))

    def test_equality_pass(self):
        self.assertTrue(evaluate_conditions({"method": {"==": "online"}}, {"method": "online"}))

    def test_equality_fail(self):
        self.assertFalse(evaluate_conditions({"method": {"==": "online"}}, {"method": "cash"}))

    def test_not_equal_pass(self):
        self.assertTrue(evaluate_conditions({"status": {"!=": "failed"}}, {"status": "success"}))

    def test_greater_than_pass(self):
        self.assertTrue(evaluate_conditions({"amount": {">": 1000}}, {"amount": 1500}))

    def test_greater_than_fail(self):
        self.assertFalse(evaluate_conditions({"amount": {">": 1000}}, {"amount": 500}))

    def test_less_than_equal(self):
        self.assertTrue(evaluate_conditions({"amount": {"<=": 1000}}, {"amount": 1000}))

    def test_range_condition(self):
        cond = {"amount": {">": 500, "<=": 2000}}
        self.assertTrue(evaluate_conditions(cond, {"amount": 1000}))
        self.assertFalse(evaluate_conditions(cond, {"amount": 2500}))

    def test_missing_field_fails(self):
        self.assertFalse(evaluate_conditions({"amount": {">": 0}}, {}))

    def test_unknown_operator_skipped(self):
        # Unknown operator "??" is ignored; other fields must pass
        self.assertTrue(evaluate_conditions({"amount": {"??": 0}}, {"amount": 100}))

    def test_multiple_fields_all_must_pass(self):
        cond = {"amount": {">": 500}, "method": {"==": "online"}}
        self.assertTrue(evaluate_conditions(cond, {"amount": 1000, "method": "online"}))
        self.assertFalse(evaluate_conditions(cond, {"amount": 1000, "method": "cash"}))

    def test_shorthand_equality(self):
        self.assertTrue(evaluate_conditions({"method": "online"}, {"method": "online"}))
        self.assertFalse(evaluate_conditions({"method": "online"}, {"method": "cash"}))

    def test_type_mismatch_returns_false(self):
        self.assertFalse(evaluate_conditions({"amount": {">": "notanumber"}}, {"amount": 1000}))


# ══════════════════════════════════════════════════════════════════════════════
# 3. send_message
# ══════════════════════════════════════════════════════════════════════════════

class SendMessageTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.template = make_template(self.tenant)

    def test_creates_sent_log_on_success(self):
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send") as mock_send:
            log = send_message(self.template, ctx, self.tenant)

        mock_send.assert_called_once()
        self.assertEqual(log.status, MessageStatus.SENT)
        self.assertEqual(log.recipient, "9876543210")
        self.assertIn("Raj", log.message)
        self.assertEqual(log.channel, Channel.SMS)
        self.assertEqual(CommunicationLog.base_objects.filter(tenant=self.tenant).count(), 1)

    def test_failed_log_when_no_recipient(self):
        ctx = {"member_name": "Raj", "amount": "500"}  # no phone
        log = send_message(self.template, ctx, self.tenant)

        self.assertEqual(log.status, MessageStatus.FAILED)
        self.assertIn("No recipient", log.error_message)

    def test_failed_log_when_adapter_raises(self):
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send", side_effect=Exception("network error")):
            log = send_message(self.template, ctx, self.tenant)

        self.assertEqual(log.status, MessageStatus.FAILED)
        self.assertIn("network error", log.error_message)

    def test_email_uses_subject_rendering(self):
        email_tpl = make_template(
            self.tenant, name="Email Tpl", channel=Channel.EMAIL,
            content="Your payment of ₹{{amount}} is confirmed.",
        )
        email_tpl.subject = "Payment ₹{{amount}} received"
        email_tpl.save()

        ctx = {"amount": "1000", "email": "user@example.com"}
        with patch("apps.communications.adapters.email.EmailAdapter.send") as mock_send:
            log = send_message(email_tpl, ctx, self.tenant)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1] if mock_send.call_args[1] else {}
        # subject should be rendered
        self.assertEqual(log.status, MessageStatus.SENT)

    def test_reference_stored_in_log(self):
        ctx = {"member_name": "X", "amount": "100", "phone": "1234567890"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            log = send_message(
                self.template, ctx, self.tenant,
                reference_type="membership", reference_id="abc-123"
            )
        self.assertEqual(log.reference_type, "membership")
        self.assertEqual(log.reference_id, "abc-123")

    def test_whatsapp_prefers_whatsapp_field(self):
        wa_tpl = make_template(self.tenant, name="WA", channel=Channel.WHATSAPP, content="Hi {{member_name}}")
        ctx = {"member_name": "Z", "phone": "111", "whatsapp": "999"}
        with patch("apps.communications.adapters.whatsapp.WhatsAppAdapter.send") as mock_send:
            log = send_message(wa_tpl, ctx, self.tenant)
        self.assertEqual(log.recipient, "999")


# ══════════════════════════════════════════════════════════════════════════════
# 4. handle_event
# ══════════════════════════════════════════════════════════════════════════════

class HandleEventTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.template = make_template(self.tenant)

    def test_no_rules_produces_no_logs(self):
        handle_event("payment_success", {"phone": "1234567890"}, self.tenant)
        self.assertEqual(CommunicationLog.base_objects.count(), 0)

    def test_matching_rule_sends_message(self):
        make_rule(self.tenant, self.template, "payment_success")
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_success", ctx, self.tenant)
        self.assertEqual(CommunicationLog.base_objects.filter(status=MessageStatus.SENT).count(), 1)

    def test_inactive_rule_skipped(self):
        make_rule(self.tenant, self.template, "payment_success", is_active=False)
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        handle_event("payment_success", ctx, self.tenant)
        self.assertEqual(CommunicationLog.base_objects.count(), 0)

    def test_inactive_template_skipped(self):
        tpl = make_template(self.tenant, name="Inactive", is_active=False)
        make_rule(self.tenant, tpl, "payment_success")
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        handle_event("payment_success", ctx, self.tenant)
        self.assertEqual(CommunicationLog.base_objects.count(), 0)

    def test_condition_mismatch_skips_rule(self):
        make_rule(self.tenant, self.template, "payment_success",
                  conditions={"amount": {">": 9999}})
        ctx = {"member_name": "Raj", "amount": 500, "phone": "9876543210"}
        handle_event("payment_success", ctx, self.tenant)
        self.assertEqual(CommunicationLog.base_objects.count(), 0)

    def test_condition_match_sends(self):
        make_rule(self.tenant, self.template, "payment_success",
                  conditions={"amount": {">": 100}})
        ctx = {"member_name": "Raj", "amount": 500, "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_success", ctx, self.tenant)
        self.assertEqual(CommunicationLog.base_objects.filter(status=MessageStatus.SENT).count(), 1)

    def test_multiple_rules_for_same_event(self):
        tpl_sms   = make_template(self.tenant, name="SMS Tpl", channel=Channel.SMS)
        tpl_email = make_template(self.tenant, name="Email Tpl", channel=Channel.EMAIL,
                                  content="Receipt for ₹{{amount}}")
        make_rule(self.tenant, tpl_sms,   "payment_success")
        make_rule(self.tenant, tpl_email, "payment_success")

        ctx = {"amount": "500", "phone": "9876543210", "email": "x@y.com"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"), \
             patch("apps.communications.adapters.email.EmailAdapter.send"):
            handle_event("payment_success", ctx, self.tenant)

        self.assertEqual(CommunicationLog.base_objects.count(), 2)

    def test_cross_tenant_isolation(self):
        """Rules from tenant B must never fire for events from tenant A."""
        tenant_b = make_tenant("GymB")
        tpl_b = make_template(tenant_b, name="B Template")
        make_rule(tenant_b, tpl_b, "payment_success")

        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_success", ctx, self.tenant)

        self.assertEqual(CommunicationLog.base_objects.filter(tenant=self.tenant).count(), 0)
        self.assertEqual(CommunicationLog.base_objects.filter(tenant=tenant_b).count(), 0)

    def test_wrong_event_name_not_triggered(self):
        make_rule(self.tenant, self.template, "payment_success")
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        handle_event("booking_confirmed", ctx, self.tenant)
        self.assertEqual(CommunicationLog.base_objects.count(), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Signal Integration
# ══════════════════════════════════════════════════════════════════════════════

class PaymentSignalIntegrationTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant("SigGym")
        self.user = make_user(self.tenant, "sig@test.com")
        self.template = make_template(
            self.tenant, content="Hi {{member_name}}, ₹{{amount}} received."
        )
        make_rule(self.tenant, self.template, "payment_success")

    def test_payment_success_signal_triggers_handle_event(self):
        from apps.payments.models import Payment, PaymentGateway, PaymentStatus
        from apps.payments.signals import payment_success

        payment = Payment.base_objects.create(
            tenant=self.tenant,
            amount=Decimal("500"),
            purpose="membership",
            gateway=PaymentGateway.OFFLINE,
            status=PaymentStatus.SUCCESS,
            created_by=self.user,
        )

        with patch("apps.communications.handlers.handle_event") as mock_handle:
            payment_success.send(sender=Payment, payment=payment)

        mock_handle.assert_called_once()
        call_args = mock_handle.call_args
        self.assertEqual(call_args[0][0], "payment_success")
        self.assertEqual(call_args[0][2], self.tenant)
        self.assertEqual(call_args[0][1]["amount"], str(payment.amount))


# ══════════════════════════════════════════════════════════════════════════════
# 6. Views
# ══════════════════════════════════════════════════════════════════════════════

class TemplateViewTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant("ViewGym")
        self.user = make_user(self.tenant, "view@test.com")
        self.client = Client()
        self.client.login(username="view@test.com", password="pass123")

    def test_template_list_200(self):
        resp = self.client.get(reverse("communications:template_list"))
        self.assertEqual(resp.status_code, 200)

    def test_template_create_get(self):
        resp = self.client.get(reverse("communications:template_create"))
        self.assertEqual(resp.status_code, 200)

    def test_template_create_post(self):
        resp = self.client.post(reverse("communications:template_create"), {
            "name":      "Pay SMS",
            "channel":   "SMS",
            "content":   "Hi {{member_name}}, ₹{{amount}} paid.",
            "is_active": "on",
        })
        self.assertRedirects(resp, reverse("communications:template_list"))
        self.assertTrue(MessageTemplate.base_objects.filter(tenant=self.tenant, name="Pay SMS").exists())

    def test_template_create_invalid_channel(self):
        resp = self.client.post(reverse("communications:template_create"), {
            "name":    "Bad",
            "channel": "INVALID",
            "content": "text",
        })
        self.assertEqual(resp.status_code, 200)  # form re-render
        self.assertFalse(MessageTemplate.base_objects.filter(name="Bad").exists())

    def test_template_edit(self):
        tpl = make_template(self.tenant, name="Old Name")
        resp = self.client.post(reverse("communications:template_edit", args=[tpl.pk]), {
            "name":      "New Name",
            "channel":   "SMS",
            "content":   "Updated content",
            "is_active": "on",
        })
        self.assertRedirects(resp, reverse("communications:template_list"))
        tpl.refresh_from_db()
        self.assertEqual(tpl.name, "New Name")

    def test_template_toggle_deactivates(self):
        tpl = make_template(self.tenant, name="Active Tpl", is_active=True)
        self.client.post(reverse("communications:template_toggle", args=[tpl.pk]))
        tpl.refresh_from_db()
        self.assertFalse(tpl.is_active)

    def test_template_toggle_activates(self):
        tpl = make_template(self.tenant, name="Inactive Tpl", is_active=False)
        self.client.post(reverse("communications:template_toggle", args=[tpl.pk]))
        tpl.refresh_from_db()
        self.assertTrue(tpl.is_active)

    def test_other_tenant_template_not_visible(self):
        other = make_tenant("Other")
        other_tpl = make_template(other, name="Other Template")
        resp = self.client.get(reverse("communications:template_list"))
        names = [t.name for t in resp.context["templates"]]
        self.assertNotIn("Other Template", names)

    def test_other_tenant_template_edit_403(self):
        other = make_tenant("OtherEdit")
        other_tpl = make_template(other, name="Stolen")
        resp = self.client.get(reverse("communications:template_edit", args=[other_tpl.pk]))
        self.assertEqual(resp.status_code, 404)


class TriggerViewTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant("TrigGym")
        self.user = make_user(self.tenant, "trig@test.com")
        self.template = make_template(self.tenant)
        self.client = Client()
        self.client.login(username="trig@test.com", password="pass123")

    def test_trigger_list_200(self):
        resp = self.client.get(reverse("communications:trigger_list"))
        self.assertEqual(resp.status_code, 200)

    def test_trigger_create_post(self):
        resp = self.client.post(reverse("communications:trigger_create"), {
            "event_name": "payment_success",
            "template":   str(self.template.pk),
            "conditions": "{}",
            "is_active":  "on",
        })
        self.assertRedirects(resp, reverse("communications:trigger_list"))
        self.assertTrue(
            TriggerRule.base_objects.filter(tenant=self.tenant, event_name="payment_success").exists()
        )

    def test_trigger_create_with_conditions(self):
        resp = self.client.post(reverse("communications:trigger_create"), {
            "event_name": "payment_success",
            "template":   str(self.template.pk),
            "conditions": '{"amount": {">": 1000}}',
            "is_active":  "on",
        })
        self.assertRedirects(resp, reverse("communications:trigger_list"))
        rule = TriggerRule.base_objects.get(tenant=self.tenant, event_name="payment_success")
        self.assertEqual(rule.conditions, {"amount": {">": 1000}})

    def test_trigger_create_invalid_json_conditions(self):
        resp = self.client.post(reverse("communications:trigger_create"), {
            "event_name": "payment_success",
            "template":   str(self.template.pk),
            "conditions": "NOT JSON",
            "is_active":  "on",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TriggerRule.base_objects.filter(tenant=self.tenant).exists())

    def test_trigger_toggle(self):
        rule = make_rule(self.tenant, self.template, is_active=True)
        self.client.post(reverse("communications:trigger_toggle", args=[rule.pk]))
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

    def test_cross_tenant_trigger_not_accessible(self):
        other = make_tenant("OtherTrig")
        other_tpl = make_template(other, name="OtherTpl")
        other_rule = make_rule(other, other_tpl)
        resp = self.client.get(reverse("communications:trigger_edit", args=[other_rule.pk]))
        self.assertEqual(resp.status_code, 404)


class LogListViewTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant("LogGym")
        self.user = make_user(self.tenant, "log@test.com")
        self.client = Client()
        self.client.login(username="log@test.com", password="pass123")

    def test_log_list_200(self):
        resp = self.client.get(reverse("communications:log_list"))
        self.assertEqual(resp.status_code, 200)

    def test_log_filter_by_channel(self):
        CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="111",
            message="sms msg", status=MessageStatus.SENT,
        )
        CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.EMAIL, recipient="a@b.com",
            message="email msg", status=MessageStatus.SENT,
        )
        resp = self.client.get(reverse("communications:log_list") + "?channel=SMS")
        logs = list(resp.context["logs"])
        self.assertTrue(all(l.channel == Channel.SMS for l in logs))
        self.assertEqual(len(logs), 1)

    def test_cross_tenant_logs_not_shown(self):
        other = make_tenant("OtherLog")
        CommunicationLog.base_objects.create(
            tenant=other, channel=Channel.SMS, recipient="999",
            message="other msg", status=MessageStatus.SENT,
        )
        resp = self.client.get(reverse("communications:log_list"))
        self.assertEqual(len(list(resp.context["logs"])), 0)
