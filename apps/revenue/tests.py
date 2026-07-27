"""
Phase 5.3 / 5.4 — Nudge Service + evaluate_member tests.

Tests use Django TestCase (real DB) with handle_event patched at its source
so no channel resolution or SMTP is required.

Patch target: 'apps.communications.services.communication_service.handle_event'
Because _fire() imports handle_event lazily inside the function body, we must
patch the function at its definition site — not at the nudge_service import.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils.timezone import localdate, now

from apps.core.models import Tenant, Branch
from apps.authority.models import Role
from apps.accounts.models import User
from apps.engagement.models import MemberEngagementScore
from apps.memberships.models import Membership, MembershipPlan
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services.payment_service import PaymentService
from apps.revenue.models import MemberRevenueSignal, NudgeLog, RiskLevel
from apps.revenue.services.nudge_service import trigger_payment_nudges, trigger_risk_warning
from apps.revenue.services.nudge_trigger_service import evaluate_member
from apps.revenue.services.revenue_signal_service import compute
from members.models import Member

# Patch at the source — _fire() imports handle_event lazily, so patching the
# nudge_service module attribute would not work.
HANDLE_EVENT_PATH = 'apps.communications.services.communication_service.handle_event'


# ── Fixture helpers ───────────────────────────────────────────────────────────

def make_tenant(name='TestGym'):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(' ', '-'))


def make_branch(tenant):
    return Branch.objects.create(tenant=tenant, name='Main', is_active=True)


def make_user(tenant, email='staff@test.com'):
    role = Role.objects.create(tenant=tenant, name='Manager')
    return User.objects.create_user(email=email, password='pass', tenant=tenant, role=role)


def make_member(tenant, user, branch, suffix=''):
    m = Member.objects.create(
        tenant=tenant, created_by=user,
        first_name='Alice', last_name='Smith',
        email=f'alice{suffix}@test.com', phone='9999999999',
    )
    m.branches.add(branch)
    return m


def make_plan(tenant, branch):
    return MembershipPlan.objects.create(
        tenant=tenant, branch=branch, name='Monthly',
        plan_type='DURATION', price=1000,
        billing_cycle_type='MONTHLY', billing_interval=1,
    )


def make_membership(tenant, member, branch, plan, user, end_date, status='active'):
    ms = Membership.base_objects.create(
        tenant=tenant, member=member, branch=branch, plan=plan,
        plan_name=plan.name,
        start_date=end_date - timedelta(days=30),
        end_date=end_date,
        status=status,
        fee_amount=1000,
        created_by=user,
    )
    # save() recalculates end_date from billing cycle and sync_status_with_lifecycle()
    # overrides status based on dates — force the values the tests actually need.
    Membership.base_objects.filter(pk=ms.pk).update(end_date=end_date, status=status)
    ms.refresh_from_db()
    return ms


def make_unpaid_payment(tenant, membership, user):
    return PaymentService.create_payment(
        tenant=tenant, amount=1000, purpose='membership',
        reference_type='membership', reference_id=membership.id,
        created_by=user,
    )


def make_paid_payment(tenant, membership, user):
    p = make_unpaid_payment(tenant, membership, user)
    return PaymentService.mark_payment_success(p)


# ── evaluate_member — due reminder ────────────────────────────────────────────

class EvaluateMemberDueReminderTests(TestCase):

    def setUp(self):
        self.tenant  = make_tenant()
        self.branch  = make_branch(self.tenant)
        self.user    = make_user(self.tenant)
        self.member  = make_member(self.tenant, self.user, self.branch)
        self.plan    = make_plan(self.tenant, self.branch)
        due          = localdate() + timedelta(days=2)
        self.ms      = make_membership(self.tenant, self.member, self.branch, self.plan, self.user, due)
        self.payment = make_unpaid_payment(self.tenant, self.ms, self.user)

    @patch(HANDLE_EVENT_PATH)
    def test_due_reminder_fires(self, mock_handle):
        evaluate_member(self.member)
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], 'payment_due_reminder')

    @patch(HANDLE_EVENT_PATH)
    def test_idempotent_no_duplicate(self, mock_handle):
        evaluate_member(self.member)
        evaluate_member(self.member)
        self.assertEqual(mock_handle.call_count, 1)
        self.assertEqual(NudgeLog.objects.count(), 1)

    @patch(HANDLE_EVENT_PATH)
    def test_no_fire_if_paid(self, mock_handle):
        PaymentService.mark_payment_success(self.payment)
        evaluate_member(self.member)
        mock_handle.assert_not_called()

    @patch(HANDLE_EVENT_PATH)
    def test_wrong_due_date_no_fire(self, mock_handle):
        # Membership due in 3 days must NOT trigger a due-in-2 reminder.
        # Use a different member to avoid unique_active_membership_per_branch.
        other_member = make_member(self.tenant, self.user, self.branch, suffix='b')
        other_ms     = make_membership(
            self.tenant, other_member, self.branch, self.plan, self.user,
            localdate() + timedelta(days=3),
        )
        make_unpaid_payment(self.tenant, other_ms, self.user)
        evaluate_member(other_member)
        mock_handle.assert_not_called()


# ── evaluate_member — overdue alert ───────────────────────────────────────────

class EvaluateMemberOverdueAlertTests(TestCase):

    def setUp(self):
        self.tenant  = make_tenant()
        self.branch  = make_branch(self.tenant)
        self.user    = make_user(self.tenant)
        self.member  = make_member(self.tenant, self.user, self.branch)
        self.plan    = make_plan(self.tenant, self.branch)
        over         = localdate() - timedelta(days=1)
        self.ms      = make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user, over, status='expired'
        )
        self.payment = make_unpaid_payment(self.tenant, self.ms, self.user)

    @patch(HANDLE_EVENT_PATH)
    def test_overdue_alert_fires(self, mock_handle):
        evaluate_member(self.member)
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], 'payment_overdue_alert')

    @patch(HANDLE_EVENT_PATH)
    def test_no_fire_if_paid(self, mock_handle):
        PaymentService.mark_payment_success(self.payment)
        evaluate_member(self.member)
        mock_handle.assert_not_called()

    @patch(HANDLE_EVENT_PATH)
    def test_idempotent_overdue(self, mock_handle):
        evaluate_member(self.member)
        evaluate_member(self.member)
        self.assertEqual(mock_handle.call_count, 1)


# ── evaluate_member — payment isolation ───────────────────────────────────────

class EvaluateMemberPaymentIsolationTests(TestCase):
    """Each payment gets its own NudgeLog row — paying one must not suppress another."""

    def setUp(self):
        self.tenant   = make_tenant()
        self.branch   = make_branch(self.tenant)
        self.user     = make_user(self.tenant)
        self.plan     = make_plan(self.tenant, self.branch)
        due           = localdate() + timedelta(days=2)
        self.member_a = make_member(self.tenant, self.user, self.branch, suffix='a')
        self.member_b = make_member(self.tenant, self.user, self.branch, suffix='b')
        ms_a          = make_membership(self.tenant, self.member_a, self.branch, self.plan, self.user, due)
        ms_b          = make_membership(self.tenant, self.member_b, self.branch, self.plan, self.user, due)
        self.pay_a    = make_unpaid_payment(self.tenant, ms_a, self.user)
        self.pay_b    = make_unpaid_payment(self.tenant, ms_b, self.user)

    @patch(HANDLE_EVENT_PATH)
    def test_paying_a_does_not_suppress_b(self, mock_handle):
        PaymentService.mark_payment_success(self.pay_a)
        evaluate_member(self.member_b)
        mock_handle.assert_called_once()

    @patch(HANDLE_EVENT_PATH)
    def test_both_unpaid_fire_independently(self, mock_handle):
        evaluate_member(self.member_a)
        evaluate_member(self.member_b)
        self.assertEqual(mock_handle.call_count, 2)
        self.assertEqual(NudgeLog.objects.count(), 2)


# ── evaluate_member — risk warning ────────────────────────────────────────────

class EvaluateMemberRiskWarningTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.member = make_member(self.tenant, self.user, self.branch)
        self.plan   = make_plan(self.tenant, self.branch)

    def _make_high_risk(self):
        ms = make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user,
            end_date=localdate() - timedelta(days=5), status='expired',
        )
        for _ in range(2):
            p = make_unpaid_payment(self.tenant, ms, self.user)
            Payment.base_objects.filter(pk=p.pk).update(
                created_at=now() - timedelta(days=5)
            )

    @patch(HANDLE_EVENT_PATH)
    def test_high_risk_fires_warning(self, mock_handle):
        self._make_high_risk()
        compute(self.member)   # classifies as HIGH, does NOT fire nudge directly
        signal = MemberRevenueSignal.objects.get(member=self.member)
        self.assertEqual(signal.risk_level, RiskLevel.HIGH)
        mock_handle.assert_not_called()   # compute() no longer fires nudges
        evaluate_member(self.member)      # single brain: fires overdue alerts + risk warning
        fired_events = [c[0][0] for c in mock_handle.call_args_list]
        self.assertIn('renewal_risk_warning', fired_events)
        self.assertEqual(fired_events.count('renewal_risk_warning'), 1)

    @patch(HANDLE_EVENT_PATH)
    def test_idempotent_risk_warning(self, mock_handle):
        MemberRevenueSignal.objects.create(
            member=self.member, risk_level=RiskLevel.HIGH, risk_reason='missed_2_payments'
        )
        evaluate_member(self.member)
        evaluate_member(self.member)
        self.assertEqual(mock_handle.call_count, 1)
        self.assertEqual(NudgeLog.objects.count(), 1)

    @patch(HANDLE_EVENT_PATH)
    def test_low_risk_no_warning(self, mock_handle):
        MemberEngagementScore.objects.create(
            member=self.member,
            last_engaged_at=now() - timedelta(days=1),
            last_success_at=now() - timedelta(days=1),
        )
        compute(self.member)
        evaluate_member(self.member)
        mock_handle.assert_not_called()

    @patch(HANDLE_EVENT_PATH)
    def test_medium_risk_no_warning(self, mock_handle):
        MemberRevenueSignal.objects.create(
            member=self.member, risk_level=RiskLevel.MEDIUM, risk_reason='missed_1'
        )
        evaluate_member(self.member)
        mock_handle.assert_not_called()


# ── trigger_payment_nudges (tenant sweep) ─────────────────────────────────────

class TriggerPaymentNudgesTenantSweepTests(TestCase):
    """trigger_payment_nudges delegates to evaluate_member for each member."""

    def setUp(self):
        self.tenant  = make_tenant()
        self.branch  = make_branch(self.tenant)
        self.user    = make_user(self.tenant)
        self.member  = make_member(self.tenant, self.user, self.branch)
        self.plan    = make_plan(self.tenant, self.branch)
        due          = localdate() + timedelta(days=2)
        self.ms      = make_membership(self.tenant, self.member, self.branch, self.plan, self.user, due)
        self.payment = make_unpaid_payment(self.tenant, self.ms, self.user)

    @patch(HANDLE_EVENT_PATH)
    def test_sweep_fires_due_reminder(self, mock_handle):
        trigger_payment_nudges(self.tenant)
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], 'payment_due_reminder')

    @patch(HANDLE_EVENT_PATH)
    def test_sweep_idempotent(self, mock_handle):
        trigger_payment_nudges(self.tenant)
        trigger_payment_nudges(self.tenant)
        self.assertEqual(mock_handle.call_count, 1)


# ── trigger_risk_warning (direct hook) ───────────────────────────────────────

class TriggerRiskWarningDirectTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.member = make_member(self.tenant, self.user, self.branch)

    @patch(HANDLE_EVENT_PATH)
    def test_fires_once(self, mock_handle):
        trigger_risk_warning(self.member, self.tenant)
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], 'renewal_risk_warning')

    @patch(HANDLE_EVENT_PATH)
    def test_no_duplicate_same_member(self, mock_handle):
        trigger_risk_warning(self.member, self.tenant)
        trigger_risk_warning(self.member, self.tenant)
        self.assertEqual(mock_handle.call_count, 1)
        self.assertEqual(NudgeLog.objects.count(), 1)
