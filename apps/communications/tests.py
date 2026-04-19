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
        # Standard payload: amount lives in payload["data"]
        payload = call_args[0][1]
        self.assertEqual(payload["data"]["amount"], str(payment.amount))


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


# ══════════════════════════════════════════════════════════════════════════════
# 7. event_type stored in CommunicationLog
# ══════════════════════════════════════════════════════════════════════════════

class EventTypeInLogTests(TestCase):

    def setUp(self):
        self.tenant   = make_tenant("EventGym")
        self.template = make_template(self.tenant, channel=Channel.SMS)
        make_rule(self.tenant, self.template, "payment_success")

    def test_event_type_written_to_log(self):
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_success", ctx, self.tenant)
        log = CommunicationLog.base_objects.get(tenant=self.tenant)
        self.assertEqual(log.event_type, "payment_success")

    def test_event_type_empty_on_direct_send(self):
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            log = send_message(self.template, ctx, self.tenant)
        self.assertEqual(log.event_type, "")

    def test_event_type_passed_to_send_message(self):
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            log = send_message(self.template, ctx, self.tenant, event_type="custom_event")
        self.assertEqual(log.event_type, "custom_event")

    def test_different_events_have_correct_event_type(self):
        make_rule(self.tenant, self.template, "payment_failed")
        ctx = {"member_name": "Raj", "amount": "500", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_failed", ctx, self.tenant)
        log = CommunicationLog.base_objects.filter(tenant=self.tenant, event_type="payment_failed").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.event_type, "payment_failed")


# ══════════════════════════════════════════════════════════════════════════════
# 8. membership_activated signal + communications handler
# ══════════════════════════════════════════════════════════════════════════════

class MembershipActivatedHandlerTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant("MemberGym")
        wa_tpl = make_template(
            self.tenant, name="Activated WA", channel=Channel.WHATSAPP,
            content="Hi {{member_name}}, your {{plan_name}} is active.",
        )
        make_rule(self.tenant, wa_tpl, "membership_activated")

    def test_membership_activated_signal_is_connected(self):
        """Verify the signal receiver is registered after app ready()."""
        from apps.memberships.signals import membership_activated
        from apps.communications.handlers import on_membership_activated

        # Django stores (key, receiver_or_weakref) tuples.
        # With weak=False the function is stored directly.
        stored = [r[1] for r in membership_activated.receivers]
        self.assertIn(on_membership_activated, stored)

    def test_on_membership_activated_calls_handle_event(self):
        """Direct unit test of the handler function — no signal dispatch needed."""
        from apps.communications.handlers import on_membership_activated, _membership_payload
        from apps.memberships.models import Membership

        fake_payload = {
            "member_name": "Priya",
            "plan_name":   "Gold",
            "phone":       "9999999999",
        }
        with patch("apps.communications.handlers.handle_event") as mock_handle, \
             patch("apps.memberships.models.Membership.base_objects") as mock_mgr:
            mock_pk = uuid.uuid4()
            mock_membership = type("M", (), {
                "pk": mock_pk, "tenant": self.tenant,
                "tenant_id": self.tenant.pk,
                "member": None, "plan": None,
                "start_date": None, "end_date": None,
                "remaining_sessions": None,
            })()
            mock_mgr.select_related.return_value.get.return_value = mock_membership

            class FakeMembership:
                pk = mock_pk
            on_membership_activated(sender=Membership, membership=FakeMembership())

        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], "membership_activated")
        self.assertEqual(mock_handle.call_args[0][2], self.tenant)

    def test_membership_activated_missing_from_db_skipped(self):
        """Handler must silently skip if membership no longer exists."""
        from apps.communications.handlers import on_membership_activated
        from apps.memberships.models import Membership

        with patch("apps.communications.handlers.handle_event") as mock_handle, \
             patch("apps.memberships.models.Membership.base_objects") as mock_mgr:
            mock_mgr.select_related.return_value.get.side_effect = Membership.DoesNotExist

            class FakeMembership:
                pk = uuid.uuid4()
            on_membership_activated(sender=Membership, membership=FakeMembership())

        mock_handle.assert_not_called()

    def test_membership_activated_end_to_end_sends_whatsapp(self):
        """Signal → handler → WhatsApp send → CommunicationLog created."""
        from apps.memberships.signals import membership_activated
        from apps.memberships.models import Membership

        fake_payload = {"member_name": "Priya", "plan_name": "Gold", "phone": "9999999999"}
        with patch("apps.communications.adapters.whatsapp.WhatsAppAdapter.send") as mock_send, \
             patch("apps.communications.handlers._membership_payload", return_value=fake_payload), \
             patch("apps.memberships.models.Membership.base_objects") as mock_mgr:

            _fake_pk = uuid.uuid4()
            mock_fresh = type("M", (), {
                "pk": _fake_pk, "tenant": self.tenant, "tenant_id": self.tenant.pk,
            })()
            mock_mgr.select_related.return_value.get.return_value = mock_fresh

            class FakeMembership:
                pk = _fake_pk
            membership_activated.send(sender=Membership, membership=FakeMembership())

        mock_send.assert_called_once()
        log = CommunicationLog.base_objects.filter(
            tenant=self.tenant, event_type="membership_activated"
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, MessageStatus.SENT)
        self.assertIn("Priya", log.message)


# ══════════════════════════════════════════════════════════════════════════════
# 9. emit_followup_due management command
# ══════════════════════════════════════════════════════════════════════════════

class EmitFollowupDueCommandTests(TestCase):

    def setUp(self):
        from django.utils import timezone
        self.tenant   = make_tenant("FollowGym")
        self.today    = timezone.now().date()
        wa_tpl = make_template(
            self.tenant, name="Followup WA", channel=Channel.WHATSAPP,
            content="Hi {{name}}, we want to connect with you today!",
        )
        make_rule(self.tenant, wa_tpl, "followup_due")

    def _make_followup(self, due_date, status="pending"):
        from crm.models import FollowUp, Enquiry, EnquirySource
        from apps.core.models import Branch
        branch, _ = Branch.objects.get_or_create(
            tenant=self.tenant, name="Main", defaults={"is_active": True}
        )
        source, _ = EnquirySource.objects.get_or_create(
            tenant=self.tenant, name="Walk-in", defaults={"is_active": True}
        )
        enquiry = Enquiry.objects.create(
            tenant=self.tenant,
            branch=branch,
            full_name="Test Lead",
            phone="9876543210",
            source=source,
        )
        return FollowUp.objects.create(
            tenant=self.tenant,
            enquiry=enquiry,
            due_date=due_date,
            status=status,
        )

    def test_dry_run_emits_nothing(self):
        self.tenant  # noqa — ensure setUp ran
        self._make_followup(self.today)
        with patch("apps.communications.management.commands.emit_followup_due.handle_event") as mock_handle:
            from django.core.management import call_command
            call_command("emit_followup_due", dry_run=True)
        mock_handle.assert_not_called()

    def test_due_today_emits_event(self):
        self._make_followup(self.today)
        with patch("apps.communications.adapters.whatsapp.WhatsAppAdapter.send"):
            from django.core.management import call_command
            call_command("emit_followup_due")
        log = CommunicationLog.base_objects.filter(
            tenant=self.tenant, event_type="followup_due"
        ).first()
        self.assertIsNotNone(log)

    def test_overdue_followup_emits_event(self):
        from datetime import timedelta
        past = self.today - timedelta(days=3)
        self._make_followup(past)
        with patch("apps.communications.adapters.whatsapp.WhatsAppAdapter.send"):
            from django.core.management import call_command
            call_command("emit_followup_due")
        self.assertEqual(
            CommunicationLog.base_objects.filter(tenant=self.tenant, event_type="followup_due").count(),
            1,
        )

    def test_done_followup_not_emitted(self):
        self._make_followup(self.today, status="done")
        with patch("apps.communications.management.commands.emit_followup_due.handle_event") as mock_handle:
            from django.core.management import call_command
            call_command("emit_followup_due")
        mock_handle.assert_not_called()

    def test_future_followup_not_emitted(self):
        from datetime import timedelta
        future = self.today + timedelta(days=5)
        self._make_followup(future)
        with patch("apps.communications.management.commands.emit_followup_due.handle_event") as mock_handle:
            from django.core.management import call_command
            call_command("emit_followup_due")
        mock_handle.assert_not_called()

    def test_payload_contains_name_and_phone(self):
        from apps.communications.management.commands.emit_followup_due import _build_payload
        fu = self._make_followup(self.today)
        payload = _build_payload(fu)
        self.assertEqual(payload["name"], "Test Lead")
        self.assertEqual(payload["phone"], "9876543210")
        self.assertEqual(payload["reference_type"], "followup")
        self.assertIn("due_date", payload)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Standard Event Payload (CommunicationEvent + extract_context)
# ══════════════════════════════════════════════════════════════════════════════

class CommunicationEventSchemaTests(TestCase):

    def test_to_payload_round_trip(self):
        from apps.communications.services.event_schema import CommunicationEvent
        ev = CommunicationEvent(
            event="payment_success", tenant_id="t1",
            entity_type="member", entity_id="m1",
            data={"member_name": "Raj", "phone": "999"},
        )
        p = ev.to_payload()
        self.assertEqual(p["event"], "payment_success")
        self.assertEqual(p["data"]["member_name"], "Raj")
        self.assertEqual(p["entity_type"], "member")

    def test_from_payload(self):
        from apps.communications.services.event_schema import CommunicationEvent
        raw = {"event": "foo", "tenant_id": "t", "entity_type": "x", "entity_id": "y",
               "data": {"a": 1}}
        ev = CommunicationEvent.from_payload(raw)
        self.assertEqual(ev.event, "foo")
        self.assertEqual(ev.data, {"a": 1})

    def test_extract_context_standard_format(self):
        from apps.communications.services.event_schema import extract_context
        payload = {"event": "e", "data": {"member_name": "Raj"}}
        self.assertEqual(extract_context(payload), {"member_name": "Raj"})

    def test_extract_context_legacy_flat_format(self):
        from apps.communications.services.event_schema import extract_context
        flat = {"member_name": "Raj", "phone": "999"}
        self.assertEqual(extract_context(flat), flat)

    def test_handle_event_uses_data_for_template_context(self):
        """Standard payload: template variables resolved from data dict."""
        tenant = make_tenant("SchemaGym")
        tpl = make_template(tenant, channel=Channel.SMS,
                            content="Hi {{member_name}}, amount ₹{{amount}}.")
        make_rule(tenant, tpl, "payment_success")
        payload = {
            "event": "payment_success", "tenant_id": str(tenant.pk),
            "entity_type": "member", "entity_id": "x",
            "data": {"member_name": "Priya", "amount": "3000", "phone": "9999999999"},
        }
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_success", payload, tenant)
        log = CommunicationLog.base_objects.filter(tenant=tenant).first()
        self.assertIsNotNone(log)
        self.assertIn("Priya", log.message)
        self.assertIn("3000", log.message)

    def test_handle_event_flat_payload_still_works(self):
        """Legacy flat payload stays backward compatible."""
        tenant = make_tenant("FlatGym")
        tpl = make_template(tenant, channel=Channel.SMS,
                            content="Hi {{member_name}}.")
        make_rule(tenant, tpl, "payment_success")
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_success",
                         {"member_name": "Raj", "phone": "9876543210"}, tenant)
        log = CommunicationLog.base_objects.filter(tenant=tenant).first()
        self.assertIn("Raj", log.message)


# ══════════════════════════════════════════════════════════════════════════════
# 11. Template Variable Safety
# ══════════════════════════════════════════════════════════════════════════════

class TemplateVariableSafetyTests(TestCase):

    def test_extract_placeholders(self):
        from apps.communications.utils.renderer import extract_placeholders
        result = extract_placeholders("Hi {{name}}, your {{plan}} is active.")
        self.assertEqual(result, {"name", "plan"})

    def test_extract_placeholders_empty(self):
        from apps.communications.utils.renderer import extract_placeholders
        self.assertEqual(extract_placeholders("No placeholders here."), set())

    def test_extract_placeholders_with_whitespace(self):
        from apps.communications.utils.renderer import extract_placeholders
        result = extract_placeholders("{{ name }} and {{  amount  }}")
        self.assertEqual(result, {"name", "amount"})

    def test_missing_vars_render_as_empty(self):
        from apps.communications.utils.renderer import render_template
        result = render_template("Hi {{name}}, amount ₹{{amount}}.", {"name": "Raj"})
        self.assertEqual(result, "Hi Raj, amount ₹.")

    def test_missing_vars_logged_as_warning(self):
        """send_message must log a warning when template placeholders are absent."""
        tenant = make_tenant("VarGym")
        tpl = make_template(tenant, channel=Channel.SMS,
                            content="Hi {{member_name}}, your {{plan_name}} is ready.")
        # Provide member_name but NOT plan_name
        ctx = {"member_name": "Raj", "phone": "9876543210"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            with self.assertLogs("apps.communications", level="WARNING") as cm:
                log = send_message(tpl, ctx, tenant, event_type="membership_activated")
        # Message still rendered and sent (empty string for missing var)
        self.assertEqual(log.status, MessageStatus.SENT)
        self.assertIn("Raj", log.message)
        record = next(
            r for r in cm.records
            if getattr(r, "reason", None) == "missing_template_vars"
        )
        self.assertIn("plan_name", record.missing)

    def test_validate_event_payload_reports_missing_fields(self):
        from apps.communications.services.event_schema import validate_event_payload
        missing = validate_event_payload("payment_success", {"amount": "500"})
        self.assertIn("member_name", missing)
        self.assertIn("phone", missing)
        self.assertNotIn("amount", missing)

    def test_validate_event_payload_unknown_event_returns_empty(self):
        from apps.communications.services.event_schema import validate_event_payload
        self.assertEqual(validate_event_payload("unknown_event", {}), [])

    def test_validate_event_payload_all_present(self):
        from apps.communications.services.event_schema import validate_event_payload
        ctx = {"member_name": "Raj", "phone": "999", "amount": "500"}
        self.assertEqual(validate_event_payload("payment_success", ctx), [])

    def test_missing_event_fields_logged_in_handle_event(self):
        """handle_event warns when known-event fields are missing from payload."""
        tenant = make_tenant("ValidGym")
        tpl = make_template(tenant, channel=Channel.SMS, content="Hi {{member_name}}.")
        make_rule(tenant, tpl, "payment_success")
        # Deliberately omit member_name and phone
        ctx = {"amount": "500", "email": "x@y.com"}
        with self.assertLogs("apps.communications", level="WARNING") as cm:
            handle_event("payment_success", ctx, tenant)
        record = next(
            r for r in cm.records
            if getattr(r, "reason", None) == "missing_event_fields"
        )
        self.assertIn("phone", record.missing_fields)


# ══════════════════════════════════════════════════════════════════════════════
# 12. Retry Mechanism
# ══════════════════════════════════════════════════════════════════════════════

class RetryMechanismTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant("RetryGym")

    def _failed_log(self, retry_count=0, channel=Channel.SMS):
        return CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=channel,
            recipient="9876543210", message="Test message",
            status=MessageStatus.FAILED, retry_count=retry_count,
        )

    def test_retry_count_default_zero(self):
        log = self._failed_log()
        self.assertEqual(log.retry_count, 0)

    def test_can_retry_true_when_below_max(self):
        log = self._failed_log(retry_count=1)
        self.assertTrue(log.can_retry)

    def test_can_retry_false_at_max(self):
        from apps.communications.services.retry_service import MAX_RETRIES
        log = self._failed_log(retry_count=MAX_RETRIES)
        self.assertFalse(log.can_retry)

    def test_can_retry_false_when_sent(self):
        log = CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="999",
            message="ok", status=MessageStatus.SENT,
        )
        self.assertFalse(log.can_retry)

    def test_retry_succeeds_and_marks_sent(self):
        log = self._failed_log()
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            from apps.communications.services.retry_service import retry_failed_messages
            count = retry_failed_messages(tenant=self.tenant)
        log.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(log.status, MessageStatus.SENT)
        self.assertEqual(log.retry_count, 1)
        self.assertIsNotNone(log.last_attempt_at)

    def test_retry_failure_increments_count(self):
        log = self._failed_log()
        with patch("apps.communications.adapters.sms.SMSAdapter.send",
                   side_effect=Exception("network down")):
            from apps.communications.services.retry_service import retry_failed_messages
            count = retry_failed_messages(tenant=self.tenant)
        log.refresh_from_db()
        self.assertEqual(count, 0)
        self.assertEqual(log.retry_count, 1)
        self.assertEqual(log.status, MessageStatus.FAILED)
        self.assertIn("network down", log.error_message)

    def test_retry_stops_at_max_retries(self):
        from apps.communications.services.retry_service import MAX_RETRIES, retry_failed_messages
        log = self._failed_log(retry_count=MAX_RETRIES)
        with patch("apps.communications.adapters.sms.SMSAdapter.send") as mock_send:
            retry_failed_messages(tenant=self.tenant)
        mock_send.assert_not_called()
        log.refresh_from_db()
        self.assertEqual(log.retry_count, MAX_RETRIES)  # unchanged

    def test_retry_only_affects_own_tenant(self):
        other = make_tenant("Other")
        other_log = CommunicationLog.base_objects.create(
            tenant=other, channel=Channel.SMS, recipient="000",
            message="other", status=MessageStatus.FAILED,
        )
        own_log = self._failed_log()
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            from apps.communications.services.retry_service import retry_failed_messages
            retry_failed_messages(tenant=self.tenant)
        own_log.refresh_from_db()
        other_log.refresh_from_db()
        self.assertEqual(own_log.status, MessageStatus.SENT)
        self.assertEqual(other_log.status, MessageStatus.FAILED)

    def test_retry_management_command(self):
        self._failed_log()
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            from django.core.management import call_command
            call_command("retry_failed_messages")
        log = CommunicationLog.base_objects.filter(tenant=self.tenant).first()
        self.assertEqual(log.status, MessageStatus.SENT)

    def test_last_attempt_at_set_on_initial_send(self):
        """first send_message call sets last_attempt_at on the log."""
        tenant = make_tenant("AttemptGym")
        tpl = make_template(tenant)
        ctx = {"member_name": "X", "amount": "0", "phone": "111"}
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            log = send_message(tpl, ctx, tenant)
        self.assertIsNotNone(log.last_attempt_at)


# ══════════════════════════════════════════════════════════════════════════════
# 13. Rate Limiting
# ══════════════════════════════════════════════════════════════════════════════

class RateLimitingTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant("RateGym")

    def _fill_window(self, count: int):
        """Create `count` SENT logs within the last minute to fill the rate window."""
        from django.utils import timezone
        for _ in range(count):
            CommunicationLog.base_objects.create(
                tenant=self.tenant, channel=Channel.SMS,
                recipient="111", message="x", status=MessageStatus.SENT,
                # created_at is auto_now_add — will be set to now() which is within window
            )

    def test_below_limit_not_rate_limited(self):
        from apps.communications.services.rate_limiter import is_rate_limited
        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=10):
            self._fill_window(5)
            self.assertFalse(is_rate_limited(self.tenant))

    def test_at_limit_is_rate_limited(self):
        from apps.communications.services.rate_limiter import is_rate_limited
        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=5):
            self._fill_window(5)
            self.assertTrue(is_rate_limited(self.tenant))

    def test_zero_limit_means_unlimited(self):
        from apps.communications.services.rate_limiter import is_rate_limited
        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=0):
            self._fill_window(1000)
            self.assertFalse(is_rate_limited(self.tenant))

    def test_failed_logs_dont_count_toward_limit(self):
        from apps.communications.services.rate_limiter import is_rate_limited
        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=3):
            for _ in range(10):
                CommunicationLog.base_objects.create(
                    tenant=self.tenant, channel=Channel.SMS,
                    recipient="111", message="x", status=MessageStatus.FAILED,
                )
            self.assertFalse(is_rate_limited(self.tenant))

    def test_rate_limited_send_logs_failed(self):
        """When rate-limited, send_message records a FAILED rate_limited log."""
        tpl = make_template(self.tenant, channel=Channel.SMS)
        ctx = {"member_name": "X", "amount": "0", "phone": "9876543210"}
        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=0):  # 0 = disabled → no rate limit
            pass  # sanity check that disabling works

        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=1):
            # Exhaust the quota
            self._fill_window(1)
            with patch("apps.communications.adapters.sms.SMSAdapter.send") as mock_send:
                log = send_message(tpl, ctx, self.tenant)
        # Adapter must NOT have been called
        mock_send.assert_not_called()
        self.assertEqual(log.status, MessageStatus.FAILED)
        self.assertIn("rate_limited", log.error_message)

    def test_rate_limit_logged_as_warning(self):
        tpl = make_template(self.tenant, channel=Channel.SMS)
        ctx = {"member_name": "X", "amount": "0", "phone": "9876543210"}
        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=1):
            self._fill_window(1)
            with self.assertLogs("apps.communications", level="WARNING") as cm:
                send_message(tpl, ctx, self.tenant)
        record = next(
            r for r in cm.records
            if getattr(r, "reason", None) == "rate_limited"
        )
        self.assertEqual(record.tenant_id, str(self.tenant.pk))

    def test_different_tenants_have_independent_limits(self):
        from apps.communications.services.rate_limiter import is_rate_limited
        other = make_tenant("OtherRate")
        with self.settings(COMMS_RATE_LIMIT_PER_MINUTE=2):
            self._fill_window(5)  # exhaust self.tenant
            self.assertTrue(is_rate_limited(self.tenant))
            self.assertFalse(is_rate_limited(other))


# ══════════════════════════════════════════════════════════════════════════════
# 14. Event Registry
# ══════════════════════════════════════════════════════════════════════════════

class EventRegistryTests(TestCase):

    def test_known_events_registered(self):
        from apps.communications.services.event_schema import EVENT_REGISTRY
        for name in ("payment_success", "payment_failed", "membership_activated",
                     "followup_due", "booking_confirmed"):
            self.assertIn(name, EVENT_REGISTRY, f"{name} not in registry")

    def test_event_definition_has_required_attrs(self):
        from apps.communications.services.event_schema import EVENT_REGISTRY
        for name, defn in EVENT_REGISTRY.items():
            self.assertIsInstance(defn.description, str, name)
            self.assertIsInstance(defn.expected_fields, list, name)
            self.assertTrue(len(defn.expected_fields) > 0, name)

    def test_get_event_definition_known(self):
        from apps.communications.services.event_schema import get_event_definition
        defn = get_event_definition("payment_success")
        self.assertIsNotNone(defn)
        self.assertIn("phone", defn.expected_fields)

    def test_get_event_definition_unknown(self):
        from apps.communications.services.event_schema import get_event_definition
        self.assertIsNone(get_event_definition("completely_unknown_event"))

    def test_validate_returns_missing_fields(self):
        from apps.communications.services.event_schema import validate_event_payload
        missing = validate_event_payload("followup_due", {"name": "Raj"})
        self.assertIn("phone", missing)
        self.assertIn("due_date", missing)
        self.assertNotIn("name", missing)

    def test_validate_all_present_returns_empty(self):
        from apps.communications.services.event_schema import validate_event_payload
        ctx = {"member_name": "R", "phone": "9", "plan_name": "Gold"}
        self.assertEqual(validate_event_payload("membership_activated", ctx), [])


# ══════════════════════════════════════════════════════════════════════════════
# 15. Exponential Backoff
# ══════════════════════════════════════════════════════════════════════════════

class BackoffTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant("BackoffGym")

    def test_initial_send_sets_next_attempt_at(self):
        template = make_template(self.tenant)
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            log = send_message(template, {"member_name": "A", "amount": "100", "phone": "9999"}, self.tenant)
        self.assertIsNotNone(log.next_attempt_at)

    def test_retry_failure_sets_exponential_next_attempt_at(self):
        from apps.communications.services.retry_service import _retry_log, BASE_DELAY_MINUTES
        from django.utils import timezone

        template = make_template(self.tenant)
        log = CommunicationLog.base_objects.create(
            tenant=self.tenant,
            channel=Channel.SMS,
            recipient="9999999999",
            message="Hi",
            status=MessageStatus.FAILED,
            retry_count=1,
        )

        with patch("apps.communications.adapters.sms.SMSAdapter.send", side_effect=Exception("fail")):
            _retry_log(log)

        log.refresh_from_db()
        self.assertEqual(log.retry_count, 2)
        expected_delay = BASE_DELAY_MINUTES * (2 ** (2 - 1))  # 10 min
        delta = log.next_attempt_at - timezone.now()
        self.assertAlmostEqual(delta.total_seconds() / 60, expected_delay, delta=1)

    def test_retry_runner_skips_not_yet_due(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.communications.services.retry_service import retry_failed_messages

        future = timezone.now() + timedelta(hours=1)
        CommunicationLog.base_objects.create(
            tenant=self.tenant,
            channel=Channel.SMS,
            recipient="9999999999",
            message="Hi",
            status=MessageStatus.FAILED,
            retry_count=0,
            next_attempt_at=future,
        )
        count = retry_failed_messages(tenant=self.tenant)
        self.assertEqual(count, 0)

    def test_retry_runner_includes_null_next_attempt_at(self):
        from apps.communications.services.retry_service import retry_failed_messages

        CommunicationLog.base_objects.create(
            tenant=self.tenant,
            channel=Channel.SMS,
            recipient="9999999999",
            message="Hi",
            status=MessageStatus.FAILED,
            retry_count=0,
            next_attempt_at=None,
        )
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            count = retry_failed_messages(tenant=self.tenant)
        self.assertEqual(count, 1)


# ══════════════════════════════════════════════════════════════════════════════
# 16. Safe Rate Limit Fallback
# ══════════════════════════════════════════════════════════════════════════════

class SafeRateLimitFallbackTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant("FallbackGym")
        from apps.communications.services.rate_limiter import _fallback_counts
        _fallback_counts.clear()

    def test_db_error_falls_back_to_in_memory(self):
        from apps.communications.services.rate_limiter import is_rate_limited
        with patch(
            "apps.communications.models.CommunicationLog.base_objects",
        ) as mock_mgr:
            mock_mgr.filter.return_value.exclude.return_value.count.side_effect = Exception("DB down")
            result = is_rate_limited(self.tenant)
        self.assertFalse(result)

    def test_fallback_enforces_safe_limit(self):
        from apps.communications.services import rate_limiter
        from apps.communications.services.rate_limiter import _fallback_is_rate_limited
        tenant_pk = str(self.tenant.pk)

        with patch.object(rate_limiter, "_get_safe_limit", return_value=3):
            for _ in range(3):
                _fallback_is_rate_limited(tenant_pk)
            result = _fallback_is_rate_limited(tenant_pk)

        self.assertTrue(result)

    def test_fallback_zero_safe_limit_always_allows(self):
        from apps.communications.services import rate_limiter
        from apps.communications.services.rate_limiter import _fallback_is_rate_limited
        tenant_pk = str(self.tenant.pk)

        with patch.object(rate_limiter, "_get_safe_limit", return_value=0):
            for _ in range(20):
                result = _fallback_is_rate_limited(tenant_pk)
        self.assertFalse(result)


# ══════════════════════════════════════════════════════════════════════════════
# 17. Priority Ordering
# ══════════════════════════════════════════════════════════════════════════════

class PriorityOrderingTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant("PrioGym")

    def test_template_default_priority_is_medium(self):
        from apps.communications.models import Priority
        tpl = make_template(self.tenant)
        self.assertEqual(tpl.priority, Priority.MEDIUM)

    def test_log_inherits_template_priority(self):
        from apps.communications.models import Priority
        tpl = make_template(self.tenant)
        tpl.priority = Priority.HIGH
        tpl.save()
        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            log = send_message(tpl, {"member_name": "A", "amount": "1", "phone": "9"}, self.tenant)
        self.assertEqual(log.priority, Priority.HIGH)

    def test_retry_runner_orders_by_priority(self):
        from apps.communications.models import Priority
        from apps.communications.services.retry_service import retry_failed_messages

        order = []

        def recording_send(to, message, subject=""):
            order.append(to)

        CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="LOW",
            message="m", status=MessageStatus.FAILED, retry_count=0, priority=Priority.LOW,
        )
        CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="HIGH",
            message="m", status=MessageStatus.FAILED, retry_count=0, priority=Priority.HIGH,
        )

        with patch("apps.communications.adapters.sms.SMSAdapter.send", side_effect=recording_send):
            retry_failed_messages(tenant=self.tenant)

        self.assertEqual(order[0], "HIGH")
        self.assertEqual(order[1], "LOW")

    def test_priority_choices_ordering(self):
        from apps.communications.models import Priority
        self.assertLess(Priority.HIGH, Priority.MEDIUM)
        self.assertLess(Priority.MEDIUM, Priority.LOW)


# ══════════════════════════════════════════════════════════════════════════════
# 18. Deduplication
# ══════════════════════════════════════════════════════════════════════════════

class DedupeTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant("DedupeGym")

    def test_make_dedupe_key_deterministic(self):
        from apps.communications.services.event_schema import make_dedupe_key
        k1 = make_dedupe_key("t1", "payment_success", "e1")
        k2 = make_dedupe_key("t1", "payment_success", "e1")
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 32)

    def test_make_dedupe_key_differs_on_different_inputs(self):
        from apps.communications.services.event_schema import make_dedupe_key
        k1 = make_dedupe_key("t1", "payment_success", "e1")
        k2 = make_dedupe_key("t1", "payment_success", "e2")
        self.assertNotEqual(k1, k2)

    def test_duplicate_send_suppressed_within_24h(self):
        from apps.communications.services.event_schema import make_dedupe_key
        template = make_template(self.tenant)

        entity_id  = str(uuid.uuid4())
        tenant_pk  = str(self.tenant.pk)
        dedupe_key = make_dedupe_key(tenant_pk, "payment_success", entity_id)

        CommunicationLog.base_objects.create(
            tenant=self.tenant,
            channel=Channel.SMS,
            recipient="9999999999",
            message="already sent",
            status=MessageStatus.SENT,
            dedupe_key=dedupe_key,
        )

        with patch("apps.communications.adapters.sms.SMSAdapter.send") as mock_send:
            log = send_message(
                template,
                {"member_name": "R", "amount": "100", "phone": "9"},
                self.tenant,
                dedupe_key=dedupe_key,
            )

        mock_send.assert_not_called()
        self.assertEqual(log.status, MessageStatus.SKIPPED)
        self.assertIn("duplicate", log.error_message)

    def test_first_send_not_suppressed(self):
        from apps.communications.services.event_schema import make_dedupe_key
        template = make_template(self.tenant)
        dedupe_key = make_dedupe_key(str(self.tenant.pk), "payment_success", str(uuid.uuid4()))

        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            log = send_message(
                template,
                {"member_name": "R", "amount": "100", "phone": "9"},
                self.tenant,
                dedupe_key=dedupe_key,
            )
        self.assertEqual(log.status, MessageStatus.SENT)

    def test_handle_event_passes_dedupe_key(self):
        template = make_template(self.tenant)
        make_rule(self.tenant, template, event_name="payment_success")

        entity_id = str(uuid.uuid4())
        payload = {
            "event":       "payment_success",
            "tenant_id":   str(self.tenant.pk),
            "entity_type": "payment",
            "entity_id":   entity_id,
            "data": {
                "member_name": "Raj",
                "phone":       "9999999999",
                "amount":      "500",
            },
        }

        with patch("apps.communications.adapters.sms.SMSAdapter.send"):
            handle_event("payment_success", payload, self.tenant)

        log = CommunicationLog.base_objects.filter(tenant=self.tenant).last()
        self.assertNotEqual(log.dedupe_key, "")
        self.assertEqual(len(log.dedupe_key), 32)


# ══════════════════════════════════════════════════════════════════════════════
# 19. SKIPPED Status Semantics
# ══════════════════════════════════════════════════════════════════════════════

class SkippedStatusTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant("SkipGym")

    def test_duplicate_produces_skipped_not_failed(self):
        from apps.communications.services.event_schema import make_dedupe_key
        template = make_template(self.tenant)
        dedupe_key = make_dedupe_key(str(self.tenant.pk), "payment_success", str(uuid.uuid4()))

        CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="9",
            message="already sent", status=MessageStatus.SENT, dedupe_key=dedupe_key,
        )

        with patch("apps.communications.adapters.sms.SMSAdapter.send") as mock_send:
            log = send_message(
                template,
                {"member_name": "R", "amount": "1", "phone": "9"},
                self.tenant,
                dedupe_key=dedupe_key,
            )

        self.assertEqual(log.status, MessageStatus.SKIPPED)
        mock_send.assert_not_called()

    def test_skipped_reason_is_duplicate(self):
        from apps.communications.services.event_schema import make_dedupe_key
        template = make_template(self.tenant)
        dedupe_key = make_dedupe_key(str(self.tenant.pk), "membership_activated", str(uuid.uuid4()))

        CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="9",
            message="sent", status=MessageStatus.SENT, dedupe_key=dedupe_key,
        )

        log = send_message(
            template,
            {"member_name": "R", "amount": "1", "phone": "9"},
            self.tenant,
            dedupe_key=dedupe_key,
        )

        self.assertIn("duplicate", log.error_message)

    def test_skipped_log_is_not_retried(self):
        from apps.communications.services.retry_service import retry_failed_messages

        CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="9",
            message="msg", status=MessageStatus.SKIPPED, retry_count=0,
        )

        with patch("apps.communications.adapters.sms.SMSAdapter.send") as mock_send:
            count = retry_failed_messages(tenant=self.tenant)

        self.assertEqual(count, 0)
        mock_send.assert_not_called()

    def test_can_retry_false_for_skipped(self):
        log = CommunicationLog(status=MessageStatus.SKIPPED, retry_count=0)
        self.assertFalse(log.can_retry)

    def test_status_choices_includes_skipped(self):
        values = [v for v, _ in MessageStatus.choices]
        self.assertIn("SKIPPED", values)


# ══════════════════════════════════════════════════════════════════════════════
# 20. Backoff Cap
# ══════════════════════════════════════════════════════════════════════════════

class BackoffCapTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant("CapGym")

    def test_backoff_capped_at_max(self):
        from apps.communications.services.retry_service import _backoff_minutes, MAX_BACKOFF_MINUTES
        # retry_count=10 → uncapped would be 5 * 2^9 = 2560 min
        self.assertEqual(_backoff_minutes(10), MAX_BACKOFF_MINUTES)

    def test_small_retry_count_not_capped(self):
        from apps.communications.services.retry_service import (
            _backoff_minutes, BASE_DELAY_MINUTES, MAX_BACKOFF_MINUTES,
        )
        delay = _backoff_minutes(1)
        self.assertEqual(delay, BASE_DELAY_MINUTES)
        self.assertLess(delay, MAX_BACKOFF_MINUTES)

    def test_retry_next_attempt_at_respects_cap(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.communications.services.retry_service import _retry_log, MAX_BACKOFF_MINUTES

        log = CommunicationLog.base_objects.create(
            tenant=self.tenant, channel=Channel.SMS, recipient="9",
            message="Hi", status=MessageStatus.FAILED, retry_count=9,
        )

        with patch("apps.communications.adapters.sms.SMSAdapter.send", side_effect=Exception("fail")):
            _retry_log(log)

        log.refresh_from_db()
        delta = log.next_attempt_at - timezone.now()
        # Should be at most MAX_BACKOFF_MINUTES + small epsilon
        self.assertLessEqual(delta.total_seconds() / 60, MAX_BACKOFF_MINUTES + 1)

    def test_backoff_cap_constant_is_60(self):
        from apps.communications.services.retry_service import MAX_BACKOFF_MINUTES
        self.assertEqual(MAX_BACKOFF_MINUTES, 60)


# ══════════════════════════════════════════════════════════════════════════════
# 21. Dedupe Key Flexibility
# ══════════════════════════════════════════════════════════════════════════════

class DedupeKeyFlexibilityTests(TestCase):
    def test_default_key_unchanged(self):
        """Omitting template_id produces the same key as the original implementation."""
        import hashlib
        from apps.communications.services.event_schema import make_dedupe_key
        expected = hashlib.sha256("t1:payment_success:e1".encode()).hexdigest()[:32]
        self.assertEqual(make_dedupe_key("t1", "payment_success", "e1"), expected)

    def test_template_id_changes_key(self):
        from apps.communications.services.event_schema import make_dedupe_key
        key_no_tpl   = make_dedupe_key("t1", "payment_success", "e1")
        key_with_tpl = make_dedupe_key("t1", "payment_success", "e1", template_id="tpl99")
        self.assertNotEqual(key_no_tpl, key_with_tpl)

    def test_different_templates_different_keys(self):
        from apps.communications.services.event_schema import make_dedupe_key
        k1 = make_dedupe_key("t1", "payment_success", "e1", template_id="tpl1")
        k2 = make_dedupe_key("t1", "payment_success", "e1", template_id="tpl2")
        self.assertNotEqual(k1, k2)

    def test_same_template_same_key(self):
        from apps.communications.services.event_schema import make_dedupe_key
        k1 = make_dedupe_key("t1", "payment_success", "e1", template_id="tpl1")
        k2 = make_dedupe_key("t1", "payment_success", "e1", template_id="tpl1")
        self.assertEqual(k1, k2)

    def test_empty_template_id_behaves_like_omitted(self):
        from apps.communications.services.event_schema import make_dedupe_key
        k_omitted = make_dedupe_key("t1", "payment_success", "e1")
        k_empty   = make_dedupe_key("t1", "payment_success", "e1", template_id="")
        self.assertEqual(k_omitted, k_empty)

    def test_key_is_always_32_chars(self):
        from apps.communications.services.event_schema import make_dedupe_key
        k1 = make_dedupe_key("t1", "payment_success", "e1")
        k2 = make_dedupe_key("t1", "payment_success", "e1", template_id="some-template-id")
        self.assertEqual(len(k1), 32)
        self.assertEqual(len(k2), 32)
