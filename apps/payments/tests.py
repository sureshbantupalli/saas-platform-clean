"""
Payments module tests.

Covers:
  - create_payment()
  - mark_payment_success() — idempotency, membership activation signal
  - mark_payment_failed()
  - duplicate webhook guard (DUPLICATE_SKIP event)
  - PaymentEvent audit log completeness
  - HTTP: mark-success, mark-failed, detail
  - Membership activation on payment success
"""

from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Tenant, Branch
from members.models import Member
from apps.memberships.models import Membership, MembershipPlan
from apps.payments.models import Payment, PaymentEvent, PaymentStatus
from apps.payments.services.payment_service import PaymentService, PaymentError


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

def make_tenant(name="TestGym"):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(" ", "-"))


def make_branch(tenant, name="Main"):
    return Branch.objects.create(tenant=tenant, name=name, is_active=True)


def make_user(tenant, email="staff@test.com"):
    role = Role.objects.create(tenant=tenant, name="Manager")
    return User.objects.create_user(email=email, password="testpass123", tenant=tenant, role=role)


def make_member(tenant, user):
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name="Alice", last_name="Smith", email="alice@test.com"
    )


def make_plan(tenant, branch):
    return MembershipPlan.objects.create(
        tenant=tenant, branch=branch, name="Monthly",
        plan_type="DURATION", price=1000,
        billing_cycle_type="MONTHLY", billing_interval=1,
    )


def make_membership(tenant, member, branch, plan, user):
    from datetime import date
    return Membership.base_objects.create(
        tenant=tenant, member=member, branch=branch, plan=plan,
        plan_name=plan.name, start_date=date.today(), end_date=date.today(),
        status="active", payment_status="paid", amount_paid=plan.price,
        fee_amount=plan.price, created_by=user,
    )


def make_payment(tenant, user, amount=1000, reference_id=None, reference_type="membership"):
    return PaymentService.create_payment(
        tenant=tenant,
        amount=amount,
        purpose="membership",
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=user,
    )


# ══════════════════════════════════════════════════════════════
# 1. Create Payment
# ══════════════════════════════════════════════════════════════

class CreatePaymentTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)

    def test_creates_payment_with_created_status(self):
        payment = make_payment(self.tenant, self.user)
        self.assertEqual(payment.status, PaymentStatus.CREATED)
        self.assertEqual(payment.tenant, self.tenant)

    def test_creates_event_log_entry(self):
        payment = make_payment(self.tenant, self.user)
        events = PaymentEvent.objects.filter(payment=payment)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().event_type, "CREATED")

    def test_payment_linked_to_reference(self):
        import uuid
        ref_id = uuid.uuid4()
        payment = make_payment(self.tenant, self.user, reference_id=ref_id)
        self.assertEqual(payment.reference_type, "membership")
        self.assertEqual(payment.reference_id, ref_id)


# ══════════════════════════════════════════════════════════════
# 2. Mark Success
# ══════════════════════════════════════════════════════════════

class MarkSuccessTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)
        self.payment = make_payment(self.tenant, self.user)

    def test_marks_payment_as_success(self):
        PaymentService.mark_payment_success(self.payment, payment_method="cash")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertIsNotNone(self.payment.paid_at)

    def test_success_logs_event(self):
        PaymentService.mark_payment_success(self.payment)
        self.assertTrue(
            PaymentEvent.objects.filter(payment=self.payment, event_type="SUCCESS").exists()
        )

    def test_idempotent_double_success_logs_duplicate_skip(self):
        PaymentService.mark_payment_success(self.payment)
        PaymentService.mark_payment_success(self.payment)  # second call
        skip_events = PaymentEvent.objects.filter(payment=self.payment, event_type="DUPLICATE_SKIP")
        self.assertEqual(skip_events.count(), 1)

    def test_status_stays_success_after_second_call(self):
        PaymentService.mark_payment_success(self.payment)
        PaymentService.mark_payment_success(self.payment)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)


# ══════════════════════════════════════════════════════════════
# 3. Mark Failed
# ══════════════════════════════════════════════════════════════

class MarkFailedTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)

    def test_marks_payment_as_failed(self):
        payment = make_payment(self.tenant, self.user)
        PaymentService.mark_payment_failed(payment, reason="insufficient funds")
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)

    def test_failed_logs_event(self):
        payment = make_payment(self.tenant, self.user)
        PaymentService.mark_payment_failed(payment, reason="test")
        self.assertTrue(
            PaymentEvent.objects.filter(payment=payment, event_type="FAILED").exists()
        )

    def test_cannot_fail_successful_payment(self):
        payment = make_payment(self.tenant, self.user)
        PaymentService.mark_payment_success(payment)
        with self.assertRaises(PaymentError):
            PaymentService.mark_payment_failed(payment, reason="oops")

    def test_failed_payment_status_immutable(self):
        payment = make_payment(self.tenant, self.user)
        PaymentService.mark_payment_success(payment)
        try:
            PaymentService.mark_payment_failed(payment)
        except PaymentError:
            pass
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)


# ══════════════════════════════════════════════════════════════
# 4. Membership Activation via Signal
# ══════════════════════════════════════════════════════════════

class MembershipActivationTests(TestCase):

    def setUp(self):
        self.tenant  = make_tenant()
        self.user    = make_user(self.tenant)
        self.branch  = make_branch(self.tenant)
        self.member  = make_member(self.tenant, self.user)
        self.member.branches.add(self.branch)
        self.plan    = make_plan(self.tenant, self.branch)
        # Membership starts unpaid/pending (real default behaviour)
        from datetime import date
        from apps.memberships.models import Membership
        self.membership = Membership.base_objects.create(
            tenant=self.tenant, member=self.member, branch=self.branch, plan=self.plan,
            plan_name=self.plan.name, start_date=date.today(), end_date=date.today(),
            status="pending", payment_status="unpaid", amount_paid=0,
            fee_amount=self.plan.price, created_by=self.user,
        )

    def _mark_success(self, payment, **kwargs):
        """Wraps mark_payment_success so on_commit callbacks fire inside TestCase."""
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(payment, **kwargs)

    def test_full_payment_activates_membership(self):
        """Paying the full amount sets status=active, payment_status=paid."""
        payment = make_payment(
            self.tenant, self.user,
            amount=self.plan.price,
            reference_id=self.membership.pk,
            reference_type="membership",
        )
        self._mark_success(payment)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.payment_status, "paid")
        self.assertEqual(self.membership.amount_paid, self.plan.price)
        self.assertEqual(self.membership.balance_amount, 0)

    def test_partial_payment_keeps_membership_pending(self):
        """Partial payment sets payment_status=partial, membership stays pending."""
        payment = make_payment(
            self.tenant, self.user,
            amount=500,
            reference_id=self.membership.pk,
            reference_type="membership",
        )
        self._mark_success(payment)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "pending")
        self.assertEqual(self.membership.payment_status, "partial")
        self.assertEqual(self.membership.amount_paid, 500)
        self.assertEqual(self.membership.balance_amount, 500)

    def test_two_partial_payments_activate_membership(self):
        """Two partial payments totalling full amount → membership active."""
        p1 = make_payment(self.tenant, self.user, amount=600,
                          reference_id=self.membership.pk, reference_type="membership")
        p2 = make_payment(self.tenant, self.user, amount=400,
                          reference_id=self.membership.pk, reference_type="membership")
        self._mark_success(p1)
        self._mark_success(p2)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.payment_status, "paid")
        self.assertEqual(self.membership.amount_paid, 1000)

    def test_unrelated_payment_does_not_affect_membership(self):
        import uuid
        payment = make_payment(
            self.tenant, self.user,
            reference_type="booking",
            reference_id=uuid.uuid4(),
        )
        self._mark_success(payment)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "pending")
        self.assertEqual(self.membership.payment_status, "unpaid")

    def test_full_workflow_create_mark_success_membership_active(self):
        """Full flow: membership → payment CREATED → SUCCESS → membership active."""
        payment = PaymentService.create_payment(
            tenant=self.tenant,
            amount=self.membership.fee_amount,
            purpose="membership",
            reference_type="membership",
            reference_id=self.membership.pk,
            payment_method="cash",
            created_by=self.user,
        )
        self.assertEqual(payment.status, PaymentStatus.CREATED)

        with self.captureOnCommitCallbacks(execute=True):
            PaymentService.mark_payment_success(
                payment, payment_method="cash", payment_reference="CASH-001"
            )
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(payment.payment_method, "cash")
        self.assertEqual(payment.payment_reference, "CASH-001")

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.payment_status, "paid")


# ══════════════════════════════════════════════════════════════
# 5. HTTP View Tests
# ══════════════════════════════════════════════════════════════

class PaymentViewTests(TestCase):

    def setUp(self):
        self.tenant  = make_tenant()
        self.user    = make_user(self.tenant)
        self.client  = Client()
        self.client.login(username="staff@test.com", password="testpass123")
        self.payment = make_payment(self.tenant, self.user)

    def test_payment_detail_returns_200(self):
        url = reverse("payments:payment_detail", args=[self.payment.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(self.payment.id))

    def test_payment_list_returns_200(self):
        response = self.client.get(reverse("payments:payment_list"))
        self.assertEqual(response.status_code, 200)

    def test_mark_success_via_post(self):
        url = reverse("payments:payment_mark_success", args=[self.payment.pk])
        response = self.client.post(url, {
            "payment_method": "cash",
            "payment_reference": "CASH-001",
        })
        self.assertRedirects(
            response,
            reverse("payments:payment_detail", args=[self.payment.pk]),
            fetch_redirect_response=False
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)

    def test_mark_failed_via_post(self):
        url = reverse("payments:payment_mark_failed", args=[self.payment.pk])
        response = self.client.post(url, {"reason": "rejected"})
        self.assertRedirects(
            response,
            reverse("payments:payment_detail", args=[self.payment.pk]),
            fetch_redirect_response=False
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)

    def test_cannot_mark_failed_a_paid_payment_via_http(self):
        PaymentService.mark_payment_success(self.payment)
        url = reverse("payments:payment_mark_failed", args=[self.payment.pk])
        response = self.client.post(url, {"reason": "mistake"})
        # Should redirect back with error message, not crash
        self.assertEqual(response.status_code, 302)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESS)


# ══════════════════════════════════════════════════════════════
# 6. Query Helper Tests
# ══════════════════════════════════════════════════════════════

class PaymentQueryTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user   = make_user(self.tenant)
        import uuid
        self.ref_id = uuid.uuid4()

    def test_get_payments_for_reference(self):
        p1 = make_payment(self.tenant, self.user, reference_id=self.ref_id)
        p2 = make_payment(self.tenant, self.user, reference_id=self.ref_id)
        results = PaymentService.get_payments_for_reference("membership", self.ref_id)
        self.assertEqual(results.count(), 2)

    def test_get_active_payment_excludes_failed(self):
        p_fail = make_payment(self.tenant, self.user, reference_id=self.ref_id)
        PaymentService.mark_payment_failed(p_fail, reason="test")
        p_good = make_payment(self.tenant, self.user, reference_id=self.ref_id)
        result = PaymentService.get_active_payment_for_reference("membership", self.ref_id)
        self.assertEqual(result.pk, p_good.pk)
