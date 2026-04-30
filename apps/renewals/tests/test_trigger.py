import uuid
from datetime import date, timedelta
from unittest.mock import call, patch

from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Branch, Tenant
from apps.memberships.models import Membership, MembershipPlan
from apps.renewals.models import RenewalTriggerLog, TriggerType
from apps.renewals.trigger import RenewalTriggerService
from members.models import Member


# ---------------------------------------------------------------------------
# Fixtures (mirrored from test_detection so each file is self-contained)
# ---------------------------------------------------------------------------

def _tenant(name='TriggerGym'):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(' ', '-'))


def _branch(tenant, name='Main'):
    return Branch.objects.create(tenant=tenant, name=name, is_active=True)


def _user(tenant, email='staff@trigger.test'):
    role = Role.objects.create(tenant=tenant, name='Admin')
    return User.objects.create_user(email=email, password='pass', tenant=tenant, role=role)


def _member(tenant, user, first='Alice', last='Test'):
    return Member.objects.create(
        tenant=tenant,
        created_by=user,
        first_name=first,
        last_name=last,
        email=f'{first.lower()}@trigger.test',
        phone='9999999999',
    )


def _membership(tenant, branch, member, user, today, end_date, status='active'):
    plan = MembershipPlan(
        tenant=tenant,
        branch=branch,
        name=f'Plan-{uuid.uuid4().hex[:8]}',
        plan_type='DURATION',
        price=0,
        billing_cycle_type='MONTHLY',
        billing_interval=1,
    )
    plan.save()
    m = Membership(
        tenant=tenant, branch=branch, member=member, plan=plan,
        start_date=today - timedelta(days=23), created_by=user,
    )
    m.save()
    Membership._base_manager.filter(id=m.id).update(end_date=end_date, status=status)
    m.refresh_from_db()
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class RenewalTriggerServiceTests(TestCase):

    TODAY = date(2026, 5, 1)

    def setUp(self):
        self.tenant = _tenant()
        self.branch = _branch(self.tenant)
        self.user   = _user(self.tenant)
        self.member = _member(self.tenant, self.user)
        self.member.branches.add(self.branch)

    def _membership(self, end_date, status='active'):
        return _membership(
            self.tenant, self.branch, self.member,
            self.user, self.TODAY, end_date, status,
        )

    # ── 1. Events fired for new items ────────────────────────────────────────

    def test_triggers_events_for_new_items(self):
        m = self._membership(self.TODAY + timedelta(days=7))

        with patch('apps.renewals.trigger.handle_event') as mock_he:
            result = RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)

        mock_he.assert_called_once()
        event_name, context, tenant_arg = mock_he.call_args[0]
        self.assertEqual(event_name, 'expiring_7d')
        self.assertEqual(tenant_arg, self.tenant)
        self.assertEqual(context['membership_id'], str(m.id))
        self.assertIn('member_name', context)
        self.assertIn('expiry_date', context)
        self.assertIn('days_left', context)
        self.assertEqual(result['triggered'], 1)
        self.assertEqual(result['skipped'], 0)

    def test_context_keys_are_complete(self):
        self._membership(self.TODAY + timedelta(days=7))
        with patch('apps.renewals.trigger.handle_event') as mock_he:
            RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)
        _, context, _ = mock_he.call_args[0]
        required_keys = {
            'member_id', 'member_name', 'phone', 'email',
            'membership_id', 'plan_name', 'expiry_date', 'days_left',
        }
        self.assertEqual(required_keys, set(context.keys()))

    # ── 2. Already-triggered items skipped ──────────────────────────────────

    def test_skips_already_triggered_items(self):
        m = self._membership(self.TODAY + timedelta(days=7))
        RenewalTriggerLog.base_objects.create(
            tenant=self.tenant,
            membership=m,
            trigger_type=TriggerType.EXPIRING_7D,
            expiry_date=m.final_end_date,
        )
        with patch('apps.renewals.trigger.handle_event') as mock_he:
            result = RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)

        mock_he.assert_not_called()
        # detect_all already filtered the logged item → triggered=0, skipped=0
        self.assertEqual(result['triggered'], 0)
        self.assertEqual(result['skipped'], 0)

    # ── 3. Log is written after successful trigger ───────────────────────────

    def test_creates_trigger_log(self):
        m = self._membership(self.TODAY + timedelta(days=7))
        with patch('apps.renewals.trigger.handle_event'):
            RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)

        self.assertTrue(
            RenewalTriggerLog.base_objects.filter(
                membership=m,
                trigger_type=TriggerType.EXPIRING_7D,
                expiry_date=m.final_end_date,
            ).exists()
        )

    # ── 4. Idempotent across multiple runs ───────────────────────────────────

    def test_idempotent_on_multiple_runs(self):
        self._membership(self.TODAY + timedelta(days=7))

        with patch('apps.renewals.trigger.handle_event') as mock_he:
            result1 = RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)
            result2 = RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)

        self.assertEqual(mock_he.call_count, 1)       # only fires on first run
        self.assertEqual(result1['triggered'], 1)
        self.assertEqual(result1['skipped'],   0)
        self.assertEqual(result2['triggered'], 0)
        self.assertEqual(result2['skipped'],   0)     # detect_all filters it out

    # ── 5. Multi-tenant isolation ────────────────────────────────────────────

    def test_multi_tenant_isolation(self):
        tenant2 = _tenant('GymB')
        branch2 = _branch(tenant2)
        user2   = _user(tenant2, 'staff@gymb.test')
        member2 = _member(tenant2, user2, first='Bob', last='Other')
        member2.branches.add(branch2)
        _membership(tenant2, branch2, member2, user2,
                    self.TODAY, self.TODAY + timedelta(days=7))

        m1 = self._membership(self.TODAY + timedelta(days=7))

        with patch('apps.renewals.trigger.handle_event') as mock_he:
            result = RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)

        self.assertEqual(result['triggered'], 1)
        # Every call must have been for tenant1, not tenant2
        for c in mock_he.call_args_list:
            self.assertEqual(c[0][2], self.tenant)

    # ── 6. IntegrityError on log write is safe ───────────────────────────────

    def test_integrity_error_handling_safe(self):
        self._membership(self.TODAY + timedelta(days=7))

        with patch('apps.renewals.trigger.handle_event'):
            with patch.object(
                RenewalTriggerLog.base_objects, 'create',
                side_effect=IntegrityError('duplicate key'),
            ):
                result = RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)

        # IntegrityError swallowed; doesn't crash; counts as skipped
        self.assertEqual(result['triggered'], 0)
        self.assertEqual(result['skipped'],   1)

    # ── 7. Correct event_name per stage ─────────────────────────────────────

    def test_event_name_matches_trigger_type_string(self):
        # Explicit check that trigger_type value flows through as event_name.
        # Phase 2's contract: event_name is always the raw trigger_type string.
        self._membership(self.TODAY + timedelta(days=1))
        with patch('apps.renewals.trigger.handle_event') as mock_he:
            RenewalTriggerService.trigger_all(self.tenant, today=self.TODAY)
        event_name = mock_he.call_args[0][0]
        self.assertEqual(event_name, 'expiring_1d')
