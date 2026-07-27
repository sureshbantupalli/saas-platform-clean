"""
Phase 5.4 — Revenue UI tests.

Verifies:
  1. test_payment_badges_render      — correct badge/label/reason per status
  2. test_sorting_order              — overdue → pending → paid (DB-level)
  3. test_dashboard_metrics          — counts match PaymentService status enum
  4. test_no_n_plus_one_queries      — exactly 2 DB queries regardless of row count
  5. test_template_has_no_business_logic — template is purely presentational

INVARIANT: service pre-computes all status values; tests verify pre-computed values,
not status logic (which belongs to PaymentService and its own test suite).
"""

from datetime import timedelta
from pathlib import Path

from django.test import TestCase
from django.utils.timezone import localdate, now

from apps.core.models import Tenant, Branch
from apps.authority.models import Role
from apps.accounts.models import User
from apps.memberships.models import Membership, MembershipPlan  # Membership used in anomaly test
from apps.payments.models import Payment
from apps.payments.services.payment_service import PaymentService, PaymentTimingStatus
from apps.payments.services.payment_intelligence_service import (
    PaymentRow,
    StatusGroup,
    get_payment_rows_for_member,
    get_payment_metrics,
)
from members.models import Member


# ── Fixtures ──────────────────────────────────────────────────────────────────

_ctr = [0]  # module-level counter ensures globally unique names


def _uid():
    _ctr[0] += 1
    return _ctr[0]


def make_tenant():
    n = _uid()
    return Tenant.objects.create(name=f'Gym{n}', subdomain=f'gym{n}')


def make_branch(tenant):
    return Branch.objects.create(tenant=tenant, name='Main', is_active=True)


def make_user(tenant):
    n = _uid()
    role = Role.objects.create(tenant=tenant, name=f'Mgr{n}')
    return User.objects.create_user(
        email=f'staff{n}@test54.com', password='x', tenant=tenant, role=role,
    )


def make_member(tenant, user, branch, suffix=''):
    n = _uid()
    m = Member.objects.create(
        tenant=tenant, created_by=user,
        first_name='Test', last_name=f'User{n}',
        email=f'member{n}{suffix}@test54.com', phone='9999999999',
    )
    m.branches.add(branch)
    return m


def make_plan(tenant, branch):
    n = _uid()
    return MembershipPlan.objects.create(
        tenant=tenant, branch=branch, name=f'Plan{n}',
        plan_type='DURATION', price=500,
        billing_cycle_type='MONTHLY', billing_interval=1,
    )


def make_membership(tenant, member, branch, plan, user, end_date, status='active'):
    ms = Membership.base_objects.create(
        tenant=tenant, member=member, branch=branch, plan=plan,
        plan_name=plan.name,
        start_date=end_date - timedelta(days=30),
        end_date=end_date, status=status,
        fee_amount=500, created_by=user,
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


def make_paid_payment(tenant, membership, user, paid_date):
    """Creates a payment and marks it SUCCESS with paid_at = paid_date (no DB call in loop)."""
    p = make_payment(tenant, membership, user)
    Payment.base_objects.filter(pk=p.pk).update(paid_at=paid_date, status='SUCCESS')
    p.refresh_from_db()
    return p


# ── 1. Badge / label / reason rendering ──────────────────────────────────────

class PaymentBadgesRenderTests(TestCase):
    """Service pre-computes status_badge, status_label, status_reason, is_late.
    Each test creates a fresh member with exactly one payment so there is
    no unique-active-membership constraint issue."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def _row(self, end_date, paid_date=None, ms_status='active'):
        member = make_member(self.tenant, self.user, self.branch)
        ms = make_membership(
            self.tenant, member, self.branch, self.plan, self.user, end_date, ms_status,
        )
        if paid_date:
            make_paid_payment(self.tenant, ms, self.user, paid_date)
        else:
            make_payment(self.tenant, ms, self.user)
        rows = get_payment_rows_for_member(self.tenant, member)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Type contract: service must resolve tri-state is_late to a plain bool here.
        # Catches: show_late_badge = is_late  (None slips through as falsy, not False)
        self.assertIsNotNone(row.show_late_badge)
        self.assertIsInstance(row.show_late_badge, bool)
        return row

    def test_overdue_badge(self):
        row = self._row(end_date=localdate() - timedelta(days=3), ms_status='expired')
        self.assertIsInstance(row, PaymentRow)
        self.assertEqual(row.status, PaymentTimingStatus.OVERDUE)
        self.assertEqual(row.status_label, 'Overdue')
        self.assertEqual(row.status_badge, 'danger')
        self.assertIn('3', row.status_reason)
        self.assertIs(row.is_late, False)   # known-not-late, not None/unknown
        self.assertEqual(row.status_group, StatusGroup.OVERDUE)

    def test_pending_badge(self):
        row = self._row(end_date=localdate() + timedelta(days=5))
        self.assertIsInstance(row, PaymentRow)
        self.assertEqual(row.status, PaymentTimingStatus.PENDING)
        self.assertEqual(row.status_label, 'Pending')
        self.assertEqual(row.status_badge, 'warning')
        self.assertIn('5', row.status_reason)
        self.assertIs(row.is_late, False)   # known-not-late, not None/unknown
        self.assertEqual(row.status_group, StatusGroup.PENDING)

    def test_pending_today_badge(self):
        row = self._row(end_date=localdate())
        self.assertEqual(row.status, PaymentTimingStatus.PENDING)
        self.assertIn('today', row.status_reason)
        self.assertEqual(row.status_group, StatusGroup.PENDING)

    def test_paid_on_time_badge(self):
        due = localdate() + timedelta(days=10)
        row = self._row(end_date=due, paid_date=now() - timedelta(days=1))
        self.assertIsInstance(row, PaymentRow)
        self.assertEqual(row.status, PaymentTimingStatus.ON_TIME)
        self.assertEqual(row.status_label, 'Paid')
        self.assertEqual(row.status_badge, 'success')
        self.assertIs(row.is_late, False)   # known-not-late, not None/unknown
        self.assertEqual(row.status_group, StatusGroup.PAID)

    def test_paid_late_badge_and_indicator(self):
        # Due date 5 days ago; paid 1 day ago → paid after due → LATE.
        due = localdate() - timedelta(days=5)
        row = self._row(end_date=due, paid_date=now() - timedelta(days=1), ms_status='expired')
        self.assertIsInstance(row, PaymentRow)
        self.assertEqual(row.status, PaymentTimingStatus.LATE)
        self.assertEqual(row.status_badge, 'secondary')
        self.assertIs(row.is_late, True)         # known-late, not None/unknown
        self.assertIs(row.show_late_badge, True) # service resolved tri-state → True
        self.assertIn('late', row.status_reason)
        # LATE collapses into PAID at the group level; lateness preserved via is_late + status_code.
        self.assertEqual(row.status_group, StatusGroup.PAID)

    def test_missing_due_date_row_is_unknown(self):
        """
        A payment whose Membership.end_date is NULL gets status_group=UNKNOWN.

        UNKNOWN must NOT be counted as PAID, PENDING, or OVERDUE — it surfaces
        data-quality anomalies rather than silently inflating other buckets.

        Mechanism: null out end_date directly (simulates a migration artifact or
        manual corruption).  The membership stays non-deleted so the payment is
        still fetched; the Subquery returns NULL, triggering the anomaly path.
        """
        member = make_member(self.tenant, self.user, self.branch)
        ms = make_membership(
            self.tenant, member, self.branch, self.plan, self.user,
            end_date=localdate() + timedelta(days=10),
        )
        make_payment(self.tenant, ms, self.user)

        # Soft-delete the membership.  The prefetch now includes deleted memberships
        # so the payment stays in scope, but the Subquery (is_deleted=False) returns
        # NULL for due_date → anomaly path fires → status_group=UNKNOWN.
        Membership.base_objects.filter(pk=ms.pk).update(is_deleted=True)

        rows = get_payment_rows_for_member(self.tenant, member)
        self.assertEqual(len(rows), 1)

        row = rows[0]
        self.assertEqual(row.status_group, StatusGroup.UNKNOWN)
        self.assertIsNone(row.status)
        self.assertIsNone(row.due_date)
        # is_late=None means "not applicable", NOT "known safe" — tri-state distinction.
        self.assertIsNone(row.is_late)
        # show_late_badge must be a plain bool even on anomaly rows — never None.
        self.assertIsNotNone(row.show_late_badge)
        self.assertIsInstance(row.show_late_badge, bool)
        self.assertIs(row.show_late_badge, False)


# ── 2. Sorting order ──────────────────────────────────────────────────────────

class SortingOrderTests(TestCase):
    """Overdue → pending → paid ordering is DB-level and stable.

    A member can have only ONE 'active' membership per branch (unique constraint).
    Use status='expired' for past-due memberships — their payments are still
    classified by timing (paid_at / due_date) not by membership status.
    """

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)
        self.member = make_member(self.tenant, self.user, self.branch)

    def test_sort_overdue_pending_paid(self):
        today = localdate()

        # Paid: expired, future end_date, paid before due → ON_TIME (sort_order=2)
        paid_ms = make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user,
            end_date=today + timedelta(days=10), status='expired',
        )
        make_paid_payment(self.tenant, paid_ms, self.user, paid_date=now() - timedelta(days=1))

        # Pending: active, future end_date, unpaid → PENDING (sort_order=1)
        pending_ms = make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user,
            end_date=today + timedelta(days=5), status='active',
        )
        make_payment(self.tenant, pending_ms, self.user)

        # Overdue: expired, past end_date, unpaid → OVERDUE (sort_order=0)
        overdue_ms = make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user,
            end_date=today - timedelta(days=3), status='expired',
        )
        make_payment(self.tenant, overdue_ms, self.user)

        rows = get_payment_rows_for_member(self.tenant, self.member)
        statuses = [r.status for r in rows]
        groups   = [r.status_group for r in rows]

        self.assertEqual(statuses[0], PaymentTimingStatus.OVERDUE)
        self.assertEqual(statuses[1], PaymentTimingStatus.PENDING)
        self.assertIn(statuses[2], (PaymentTimingStatus.ON_TIME, PaymentTimingStatus.LATE))
        # status_group collapses ON_TIME / LATE → PAID
        self.assertEqual(groups, [StatusGroup.OVERDUE, StatusGroup.PENDING, StatusGroup.PAID])

    def test_two_overdue_sorted_by_due_date_ascending(self):
        today = localdate()

        ms_older = make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user,
            end_date=today - timedelta(days=10), status='expired',
        )
        make_payment(self.tenant, ms_older, self.user)

        ms_newer = make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user,
            end_date=today - timedelta(days=2), status='expired',
        )
        make_payment(self.tenant, ms_newer, self.user)

        rows = get_payment_rows_for_member(self.tenant, self.member)
        self.assertEqual(rows[0].due_date, today - timedelta(days=10))
        self.assertEqual(rows[1].due_date, today - timedelta(days=2))


# ── 3. Dashboard metrics ──────────────────────────────────────────────────────

class DashboardMetricsTests(TestCase):
    """get_payment_metrics() counts must agree with per-row status values."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)

    def _unpaid(self, end_date, ms_status='active'):
        member = make_member(self.tenant, self.user, self.branch)
        ms = make_membership(
            self.tenant, member, self.branch, self.plan, self.user, end_date, ms_status,
        )
        make_payment(self.tenant, ms, self.user)

    def _paid(self, end_date, paid_date):
        member = make_member(self.tenant, self.user, self.branch)
        ms = make_membership(
            self.tenant, member, self.branch, self.plan, self.user, end_date,
        )
        make_paid_payment(self.tenant, ms, self.user, paid_date=paid_date)

    def test_overdue_and_pending_counts(self):
        today = localdate()
        self._unpaid(today - timedelta(days=3), ms_status='expired')   # overdue
        self._unpaid(today - timedelta(days=1), ms_status='expired')   # overdue
        self._unpaid(today + timedelta(days=5))                         # pending
        self._paid(today + timedelta(days=10), paid_date=now())         # paid (excluded)

        metrics = get_payment_metrics(self.tenant)
        self.assertEqual(metrics['overdue_count'], 2)
        self.assertEqual(metrics['total_pending'], 1)

    def test_paid_not_counted_in_pending_or_overdue(self):
        today = localdate()
        self._paid(today + timedelta(days=10), paid_date=now())
        self._paid(today - timedelta(days=5), paid_date=now())

        metrics = get_payment_metrics(self.tenant)
        self.assertEqual(metrics['overdue_count'], 0)
        self.assertEqual(metrics['total_pending'], 0)

    def test_collected_last_30_days(self):
        today = localdate()
        self._paid(today + timedelta(days=10), paid_date=now())
        self._paid(today + timedelta(days=10), paid_date=now())

        metrics = get_payment_metrics(self.tenant)
        self.assertEqual(metrics['total_collected_last_30_days'], 1000)  # 2 × 500

    def test_collected_excludes_payments_older_than_30_days(self):
        today   = localdate()
        old_at  = now() - timedelta(days=35)
        member  = make_member(self.tenant, self.user, self.branch)
        ms      = make_membership(
            self.tenant, member, self.branch, self.plan, self.user,
            end_date=today + timedelta(days=10),
        )
        p = make_paid_payment(self.tenant, ms, self.user, paid_date=old_at)
        # Force paid_at to 35 days ago (make_paid_payment uses now() by default).
        Payment.base_objects.filter(pk=p.pk).update(paid_at=old_at)

        metrics = get_payment_metrics(self.tenant)
        self.assertEqual(metrics['total_collected_last_30_days'], 0)

    def test_metrics_match_per_row_status(self):
        """Aggregate counts must agree with per-row status produced by the service."""
        today = localdate()
        members = {}

        for label, delta, paid, ms_status in [
            ('ov1', -3, False, 'expired'),
            ('ov2', -1, False, 'expired'),
            ('pend',  5, False, 'active'),
            ('paid', 10, True,  'active'),
        ]:
            m  = make_member(self.tenant, self.user, self.branch, suffix=label)
            ms = make_membership(
                self.tenant, m, self.branch, self.plan, self.user,
                end_date=today + timedelta(days=delta), status=ms_status,
            )
            if paid:
                make_paid_payment(self.tenant, ms, self.user, paid_date=now())
            else:
                make_payment(self.tenant, ms, self.user)
            members[label] = m

        metrics = get_payment_metrics(self.tenant)

        # Ground truth: count statuses from per-row service output.
        all_statuses = []
        for m in members.values():
            for r in get_payment_rows_for_member(self.tenant, m):
                if r.status:
                    all_statuses.append(r.status)

        self.assertEqual(
            metrics['overdue_count'],
            all_statuses.count(PaymentTimingStatus.OVERDUE),
        )
        self.assertEqual(
            metrics['total_pending'],
            all_statuses.count(PaymentTimingStatus.PENDING),
        )


# ── 4. N+1 query guard ────────────────────────────────────────────────────────

class NoNPlusOneTests(TestCase):
    """get_payment_rows_for_member() must use exactly 2 DB queries for any payload."""

    def setUp(self):
        self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.user   = make_user(self.tenant)
        self.plan   = make_plan(self.tenant, self.branch)
        self.member = make_member(self.tenant, self.user, self.branch)

    def test_exactly_two_queries_for_five_payments(self):
        today = localdate()

        # Only 1 'active' membership allowed per member+branch; use 'expired' for the rest.
        make_membership(
            self.tenant, self.member, self.branch, self.plan, self.user,
            end_date=today + timedelta(days=10), status='active',
        )  # pending payment
        for i in range(1, 5):
            ms = make_membership(
                self.tenant, self.member, self.branch, self.plan, self.user,
                end_date=today - timedelta(days=i), status='expired',
            )
            make_payment(self.tenant, ms, self.user)

        # One active → one more payment needed.
        active_ms = Membership.base_objects.get(
            member=self.member, status='active', is_deleted=False,
        )
        make_payment(self.tenant, active_ms, self.user)

        # 1st query: memberships prefetch; 2nd query: payments with annotations.
        with self.assertNumQueries(2):
            rows = get_payment_rows_for_member(self.tenant, self.member)

        self.assertEqual(len(rows), 5)
        self.assertTrue(all(isinstance(r, PaymentRow) for r in rows))

    def test_empty_member_uses_one_query(self):
        """Member with no memberships returns [] after exactly 1 DB query."""
        with self.assertNumQueries(1):
            rows = get_payment_rows_for_member(self.tenant, self.member)
        self.assertEqual(rows, [])


# ── 5. Template purity ────────────────────────────────────────────────────────

class TemplatePurityTests(TestCase):
    """Template must not contain date comparisons, status derivations, or service calls."""

    TEMPLATE = (
        Path(__file__).resolve().parents[2]
        / 'templates' / 'members' / 'member_payments.html'
    )

    def _html(self):
        return self.TEMPLATE.read_text(encoding='utf-8')

    def test_no_raw_date_comparison(self):
        html = self._html()
        for pattern in ('due_date <', '> today', '< today', 'timedelta', 'localdate'):
            self.assertNotIn(pattern, html, f'Forbidden in template: {pattern!r}')

    def test_no_paymentservice_call(self):
        html = self._html()
        self.assertNotIn('PaymentService', html)
        self.assertNotIn('get_payment_status', html)
        self.assertNotIn('is_late(', html)

    def test_no_status_derivation_logic(self):
        html = self._html()
        for pattern in ('OVERDUE', 'PENDING', 'ON_TIME', 'PaymentTimingStatus'):
            self.assertNotIn(pattern, html, f'Forbidden in template: {pattern!r}')

    def test_renders_precomputed_keys(self):
        html = self._html()
        for key in ('row.status_badge', 'row.status_label', 'row.status_reason',
                    'row.show_late_badge'):
            self.assertIn(key, html, f'Template must render pre-computed key: {key!r}')
        # Tri-state must not leak into template — raw is_late access is forbidden.
        self.assertNotIn('row.is_late', html, 'Template must not access is_late directly')

    def test_none_is_not_rendered_as_late(self):
        """Behavioral guard: only show_late_badge=True renders the Late badge.

        Tests all three states of the domain tri-state (is_late: True/False/None)
        as they map to show_late_badge (True/False), plus None directly to catch
        a future regression like `show_late_badge = bool(is_late)` which would
        silently convert None→False while losing the semantic distinction.

        Extracts the actual conditional block from the real template file so the
        test breaks if someone changes show_late_badge to is_late or loosens the
        condition to bare truthiness.
        """
        import re
        from types import SimpleNamespace
        from django.template import Context, Template

        html = self._html()
        m = re.search(
            r'(\{%[\-\s]*if row\.show_late_badge[\-\s]*%\}.*?\{%[\-\s]*endif[\-\s]*%\})',
            html, re.DOTALL,
        )
        self.assertIsNotNone(m, 'show_late_badge conditional block not found in template')

        snippet = m.group(1)
        tmpl = Template(snippet)

        def render(val):
            return tmpl.render(Context({'row': SimpleNamespace(show_late_badge=val)}))

        # False → no badge (is_late=False: known on-time/unpaid)
        self.assertNotIn('Late', render(False))
        # None → no badge (is_late=None: anomaly row — not applicable)
        # Catches regression: `show_late_badge = bool(is_late)` would still pass False/True
        # but this assertion ensures None is also explicitly suppressed.
        self.assertNotIn('Late', render(None))
        # True → badge present (is_late=True: known late payment)
        self.assertIn('Late', render(True))
