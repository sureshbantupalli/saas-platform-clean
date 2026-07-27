"""
Payment Intelligence Dashboard — service-layer tests.

Covers:
  • Metric definitions: pending = unpaid AND due_date >= today
                        overdue = unpaid AND due_date <  today
  • Status derived from PaymentService (not re-derived in tests)
  • Sort order: overdue (0) → pending (1) → paid (2)  — DB-level, checked here
  • Boundary: due_date == today → PENDING, never OVERDUE
  • Late indicator: paid_at > due_date
  • Risk reason surfaced on high-risk members
"""

from datetime import timedelta

from django.test import TestCase
from django.utils.timezone import localdate, now

from apps.core.models import Tenant, Branch
from apps.authority.models import Role
from apps.accounts.models import User
from apps.memberships.models import Membership, MembershipPlan
from apps.payments.models import Payment
from apps.payments.services.payment_service import PaymentService, PaymentTimingStatus
from apps.payments.services.payment_intelligence_service import (
    ALLOWED_PREFIXES,
    build_status_code,
    get_payment_intelligence,
    parse_status_code,
)
from apps.revenue.models import MemberRevenueSignal, RiskLevel
from members.models import Member


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_tenant(name='Gym'):
    return Tenant.objects.create(name=name, subdomain=name.lower())

def make_branch(tenant):
    return Branch.objects.create(tenant=tenant, name='Main', is_active=True)

def make_user(tenant):
    role = Role.objects.create(tenant=tenant, name='Manager')
    return User.objects.create_user(email='staff@test.com', password='x', tenant=tenant, role=role)

def make_member(tenant, user, branch, suffix=''):
    m = Member.objects.create(
        tenant=tenant, created_by=user,
        first_name='Alice', last_name=f'Smith{suffix}',
        email=f'alice{suffix}@test.com', phone='9999999999',
    )
    m.branches.add(branch)
    return m

def make_plan(tenant, branch):
    return MembershipPlan.objects.create(
        tenant=tenant, branch=branch, name='Monthly',
        plan_type='DURATION', price=500,
        billing_cycle_type='MONTHLY', billing_interval=1,
    )

def make_membership(tenant, member, branch, plan, user, end_date, status='active'):
    ms = Membership.base_objects.create(
        tenant=tenant, member=member, branch=branch, plan=plan,
        plan_name=plan.name,
        start_date=end_date - timedelta(days=30),
        end_date=end_date,
        status=status,
        fee_amount=500,
        created_by=user,
    )
    # Bypass save() billing-cycle recalculation and sync_status_with_lifecycle().
    Membership.base_objects.filter(pk=ms.pk).update(end_date=end_date, status=status)
    ms.refresh_from_db()
    return ms

def make_payment(tenant, membership, user):
    return PaymentService.create_payment(
        tenant=tenant, amount=500, purpose='membership',
        reference_type='membership', reference_id=membership.id,
        created_by=user,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class DashboardMetricsTests(TestCase):
    """pending and overdue counts are strict, non-overlapping."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def _make(self, end_date, suffix, status='active'):
        member = make_member(self.tenant, self.user, self.branch, suffix=suffix)
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user, end_date, status)
        return make_payment(self.tenant, ms, self.user)

    def test_pending_and_overdue_counts(self):
        today = localdate()
        self._make(today + timedelta(days=3), 'p1')   # pending
        self._make(today + timedelta(days=1), 'p2')   # pending
        self._make(today - timedelta(days=1), 'o1', 'expired')  # overdue
        self._make(today - timedelta(days=5), 'o2', 'expired')  # overdue

        data = get_payment_intelligence(self.tenant)
        self.assertEqual(data['metrics']['total_pending'], 2)
        self.assertEqual(data['metrics']['overdue_count'], 2)

    def test_paid_payment_excluded_from_metrics(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='paid')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user, today + timedelta(days=2))
        p      = make_payment(self.tenant, ms, self.user)
        PaymentService.mark_payment_success(p)

        data = get_payment_intelligence(self.tenant)
        self.assertEqual(data['metrics']['total_pending'], 0)
        self.assertEqual(data['metrics']['overdue_count'], 0)


class PaymentStatusSourceTests(TestCase):
    """Status badge values must match PaymentService.get_payment_status() exactly."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def test_overdue_status_from_service(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='ov')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 today - timedelta(days=2), status='expired')
        make_payment(self.tenant, ms, self.user)

        data = get_payment_intelligence(self.tenant)
        row  = data['rows'][0]
        # Status must equal what PaymentService returns — not a template derivation.
        expected = PaymentService.get_payment_status(row['payment'], due_date=row['due_date'])
        self.assertEqual(row['status'], expected)
        self.assertEqual(row['status'], PaymentTimingStatus.OVERDUE)

    def test_pending_status_from_service(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='pe')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 today + timedelta(days=5))
        make_payment(self.tenant, ms, self.user)

        data = get_payment_intelligence(self.tenant)
        row  = data['rows'][0]
        expected = PaymentService.get_payment_status(row['payment'], due_date=row['due_date'])
        self.assertEqual(row['status'], expected)
        self.assertEqual(row['status'], PaymentTimingStatus.PENDING)

    def test_paid_on_time_status(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='pt')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 today + timedelta(days=3))
        p = make_payment(self.tenant, ms, self.user)
        PaymentService.mark_payment_success(p)

        data = get_payment_intelligence(self.tenant)
        self.assertEqual(len(data['rows']), 1)
        self.assertEqual(data['rows'][0]['status'], PaymentTimingStatus.ON_TIME)


class SortingOrderTests(TestCase):
    """Overdue rows come before pending, paid rows come last. DB-level sort."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)
        today       = localdate()

        m_paid    = make_member(self.tenant, self.user, self.branch, suffix='paid')
        m_pending = make_member(self.tenant, self.user, self.branch, suffix='pend')
        m_overdue = make_member(self.tenant, self.user, self.branch, suffix='over')

        ms_paid    = make_membership(self.tenant, m_paid, self.branch, self.plan, self.user, today + timedelta(days=5))
        ms_pending = make_membership(self.tenant, m_pending, self.branch, self.plan, self.user, today + timedelta(days=2))
        ms_overdue = make_membership(self.tenant, m_overdue, self.branch, self.plan, self.user,
                                     today - timedelta(days=1), status='expired')

        p_paid    = make_payment(self.tenant, ms_paid, self.user)
        self.p_pending = make_payment(self.tenant, ms_pending, self.user)
        self.p_overdue = make_payment(self.tenant, ms_overdue, self.user)
        PaymentService.mark_payment_success(p_paid)

    def test_sort_overdue_before_pending_before_paid(self):
        data     = get_payment_intelligence(self.tenant)
        statuses = [r['status'] for r in data['rows']]
        self.assertEqual(statuses[0], PaymentTimingStatus.OVERDUE)
        self.assertEqual(statuses[1], PaymentTimingStatus.PENDING)
        self.assertEqual(statuses[2], PaymentTimingStatus.ON_TIME)


class PendingVsOverdueBoundaryTests(TestCase):
    """
    due_date == today → PENDING, not OVERDUE.

    This is the classic off-by-one: the payment is not yet overdue on its due date.
    PaymentService uses >= today for PENDING, so today's due date is NOT overdue.
    """

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def test_due_today_is_pending_not_overdue(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='bd')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user, today)
        make_payment(self.tenant, ms, self.user)

        data = get_payment_intelligence(self.tenant)
        self.assertEqual(len(data['rows']), 1)
        row = data['rows'][0]
        self.assertEqual(row['status'], PaymentTimingStatus.PENDING,
                         "due_date == today must be PENDING, not OVERDUE")
        self.assertEqual(data['metrics']['total_pending'], 1)
        self.assertEqual(data['metrics']['overdue_count'], 0)

    def test_due_yesterday_is_overdue(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='yd')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 today - timedelta(days=1), status='expired')
        make_payment(self.tenant, ms, self.user)

        data = get_payment_intelligence(self.tenant)
        self.assertEqual(data['rows'][0]['status'], PaymentTimingStatus.OVERDUE)
        self.assertEqual(data['metrics']['overdue_count'], 1)


class LateIndicatorTests(TestCase):
    """is_late uses same timezone-safe source as status (PaymentService.is_late)."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def test_paid_on_time_not_late(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='ol')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user, today + timedelta(days=2))
        p      = make_payment(self.tenant, ms, self.user)
        PaymentService.mark_payment_success(p)

        data = get_payment_intelligence(self.tenant)
        self.assertFalse(data['rows'][0]['is_late'])

    def test_paid_after_due_is_late(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='ll')
        # end_date is in the past so paid_at > due_date → late
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 today - timedelta(days=3), status='expired')
        p      = make_payment(self.tenant, ms, self.user)
        PaymentService.mark_payment_success(p)

        data = get_payment_intelligence(self.tenant)
        self.assertEqual(len(data['rows']), 1)
        # Paid after due_date = today > due_date
        self.assertTrue(data['rows'][0]['is_late'])

    def test_paid_on_due_date_is_not_late(self):
        # paid_at.date() == due_date → NOT late.
        # Prevents subtle timezone + equality bugs where paid_at == due_date
        # is incorrectly classified as late.
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='odd')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user, today)
        p      = make_payment(self.tenant, ms, self.user)
        PaymentService.mark_payment_success(p)  # paid_at = now(), date = today = due_date

        data = get_payment_intelligence(self.tenant)
        self.assertEqual(len(data['rows']), 1)
        row = data['rows'][0]
        self.assertFalse(row['is_late'], 'paid_at.date() == due_date must NOT be late')
        self.assertEqual(row['status'], PaymentTimingStatus.ON_TIME)


class StatusCodeReasonConsistencyTests(TestCase):
    """
    Invariant: status_reason and status_code must never drift apart.
    Tests verify that the human-readable reason and machine-readable code
    are consistent across each status type and day value.
    """

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def _get_row(self, end_date, status='active', pay=False):
        member = make_member(self.tenant, self.user, self.branch, suffix=str(end_date))
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 end_date, status=status)
        p = make_payment(self.tenant, ms, self.user)
        if pay:
            PaymentService.mark_payment_success(p)
        return get_payment_intelligence(self.tenant)['rows'][0]

    def test_overdue_code_matches_reason_days(self):
        # "overdue by 3 days" → OVERDUE_3D
        row = self._get_row(localdate() - timedelta(days=3), status='expired')
        self.assertIn('3', row['status_reason'])
        self.assertEqual(row['status_code'], 'OVERDUE_3D')

    def test_pending_today_code_matches_reason(self):
        # "due today" → PENDING_TODAY
        row = self._get_row(localdate())
        self.assertEqual(row['status_reason'], 'due today')
        self.assertEqual(row['status_code'], 'PENDING_TODAY')

    def test_pending_future_code_matches_reason_days(self):
        # "due in 5 days" → PENDING_5D
        row = self._get_row(localdate() + timedelta(days=5))
        self.assertIn('5', row['status_reason'])
        self.assertEqual(row['status_code'], 'PENDING_5D')

    def test_paid_on_time_code(self):
        # paid before due → ON_TIME
        row = self._get_row(localdate() + timedelta(days=3), pay=True)
        self.assertEqual(row['status_code'], 'ON_TIME')

    def test_paid_late_code_matches_reason_days(self):
        # paid today on a 3-day-old due date → LATE_3D
        row = self._get_row(localdate() - timedelta(days=3), status='expired', pay=True)
        # days_late = (today - due_date).days = 3
        self.assertIn('3', row['status_reason'])
        self.assertEqual(row['status_code'], 'LATE_3D')

    def test_no_zero_day_suffix_generated(self):
        # OVERDUE_0D is impossible by the status contract.
        # PENDING_0D is also impossible — build_status_code converts 0 to TODAY.
        # This is a tripwire: future refactors that "simplify" the 0 case will
        # break this test before the bug reaches production.
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='z0')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user, today)
        make_payment(self.tenant, ms, self.user)  # PENDING, due today → should be PENDING_TODAY

        data = get_payment_intelligence(self.tenant)
        for row in data['rows']:
            self.assertNotIn(
                '_0D', row['status_code'],
                f"Zero-day suffix found in {row['status_code']} — "
                "build_status_code() must emit _TODAY for days=0, never _0D",
            )
        self.assertEqual(data['rows'][0]['status_code'], 'PENDING_TODAY')

    def test_code_format_never_contains_raw_string(self):
        # All codes across pending / overdue / paid must match the canonical format.
        import re
        today = localdate()
        for days, sfx, st, pay in [
            ( 2, 'fmt_a', 'active',  False),   # PENDING_2D
            (-1, 'fmt_b', 'expired', False),   # OVERDUE_1D
            ( 0, 'fmt_c', 'active',  False),   # PENDING_TODAY
            ( 3, 'fmt_d', 'active',  True),    # ON_TIME
        ]:
            m  = make_member(self.tenant, self.user, self.branch, suffix=sfx)
            ms = make_membership(self.tenant, m, self.branch, self.plan, self.user,
                                 today + timedelta(days=days), status=st)
            p  = make_payment(self.tenant, ms, self.user)
            if pay:
                PaymentService.mark_payment_success(p)

        data    = get_payment_intelligence(self.tenant)
        # Pattern enforces the canonical build_status_code() format:
        #   prefix  = one or more uppercase letters/underscores (e.g. ON_TIME, OVERDUE)
        #   suffix  = absent | _TODAY | _{nonzero_int}D  (no leading zeros, no hyphens)
        pattern = re.compile(r'^[A-Z][A-Z_]*(_[1-9][0-9]*D|_TODAY)?$')
        for row in data['rows']:
            self.assertRegex(
                row['status_code'], pattern,
                f"Unexpected code format: {row['status_code']}",
            )


class RiskReasonDisplayTests(TestCase):
    """risk_reason is surfaced when member has a HIGH signal."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def test_high_risk_reason_in_row(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='hr')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 today - timedelta(days=1), status='expired')
        make_payment(self.tenant, ms, self.user)
        MemberRevenueSignal.objects.create(
            member=member, risk_level=RiskLevel.HIGH, risk_reason='missed_2_payments'
        )

        data = get_payment_intelligence(self.tenant)
        row  = data['rows'][0]
        self.assertEqual(row['risk_level'], RiskLevel.HIGH)
        self.assertEqual(row['risk_reason'], 'missed_2_payments')

    def test_no_signal_gives_none(self):
        today  = localdate()
        member = make_member(self.tenant, self.user, self.branch, suffix='ns')
        ms     = make_membership(self.tenant, member, self.branch, self.plan, self.user,
                                 today + timedelta(days=2))
        make_payment(self.tenant, ms, self.user)

        data = get_payment_intelligence(self.tenant)
        self.assertIsNone(data['rows'][0]['risk_level'])
        self.assertIsNone(data['rows'][0]['risk_reason'])


# ── build_status_code — prefix enforcement ────────────────────────────────────

class BuildStatusCodeTests(TestCase):
    """build_status_code() enforces ALLOWED_PREFIXES and the format contract."""

    def test_known_prefixes_do_not_raise(self):
        from apps.payments.services.payment_intelligence_service import ALLOWED_PREFIXES
        for prefix in ALLOWED_PREFIXES:
            build_status_code(prefix, None)       # no suffix
            build_status_code(prefix, 0)           # TODAY
            build_status_code(prefix, 3)           # numeric

    def test_unknown_prefix_raises(self):
        with self.assertRaises(ValueError):
            build_status_code('OVERDUE_PAYMENT', 3)

    def test_lowercase_prefix_raises(self):
        with self.assertRaises(ValueError):
            build_status_code('pending', 2)

    def test_hyphenated_prefix_raises(self):
        with self.assertRaises(ValueError):
            build_status_code('ON-TIME', None)

    def test_zero_days_produces_today_not_0d(self):
        self.assertEqual(build_status_code('PENDING', 0), 'PENDING_TODAY')
        self.assertNotEqual(build_status_code('PENDING', 0), 'PENDING_0D')

    def test_positive_days_format(self):
        self.assertEqual(build_status_code('OVERDUE', 3), 'OVERDUE_3D')
        self.assertEqual(build_status_code('LATE', 1),    'LATE_1D')

    def test_none_days_produces_bare_prefix(self):
        self.assertEqual(build_status_code('ON_TIME', None), 'ON_TIME')
        self.assertEqual(build_status_code('PAID', None),    'PAID')


# ── parse_status_code — round-trip and error cases ────────────────────────────

class ParseStatusCodeTests(TestCase):
    """parse_status_code() is the exact inverse of build_status_code()."""

    def _roundtrip(self, prefix, days):
        code = build_status_code(prefix, days)
        return parse_status_code(code)

    def test_roundtrip_overdue(self):
        self.assertEqual(self._roundtrip('OVERDUE', 3), ('OVERDUE', 3))

    def test_roundtrip_pending_today(self):
        self.assertEqual(self._roundtrip('PENDING', 0), ('PENDING', 'TODAY'))

    def test_roundtrip_pending_numeric(self):
        self.assertEqual(self._roundtrip('PENDING', 5), ('PENDING', 5))

    def test_roundtrip_on_time(self):
        self.assertEqual(self._roundtrip('ON_TIME', None), ('ON_TIME', None))

    def test_roundtrip_late(self):
        self.assertEqual(self._roundtrip('LATE', 2), ('LATE', 2))

    def test_roundtrip_paid(self):
        self.assertEqual(self._roundtrip('PAID', None), ('PAID', None))

    def test_unknown_prefix_raises(self):
        with self.assertRaises(ValueError):
            parse_status_code('UNKNOWN_3D')

    def test_leading_zero_raises(self):
        # OVERDUE_03D is not a valid code; build_status_code would never emit it
        with self.assertRaises(ValueError):
            parse_status_code('OVERDUE_03D')

    def test_hyphen_raises(self):
        with self.assertRaises(ValueError):
            parse_status_code('ON-TIME')

    def test_lowercase_raises(self):
        with self.assertRaises(ValueError):
            parse_status_code('overdue_3d')

    def test_zero_suffix_raises(self):
        # _0D is not a valid suffix; build_status_code converts 0 to _TODAY
        with self.assertRaises(ValueError):
            parse_status_code('PENDING_0D')
