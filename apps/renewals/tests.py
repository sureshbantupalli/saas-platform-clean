import uuid
from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Tenant, Branch
from apps.memberships.models import Membership, MembershipAdjustment, MembershipPlan
from apps.renewals.detection import RECOVERY_WINDOW_DAYS, RenewalDetectionService
from apps.renewals.models import RenewalTriggerLog, TriggerType
from members.models import Member


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tenant(name='RenewalGym'):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(' ', '-'))


def _branch(tenant, name='Main'):
    return Branch.objects.create(tenant=tenant, name=name, is_active=True)


def _user(tenant, email='staff@renewal.test'):
    role = Role.objects.create(tenant=tenant, name='Admin')
    return User.objects.create_user(email=email, password='pass', tenant=tenant, role=role)


def _member(tenant, user, first='Alice', last='Test'):
    return Member.objects.create(
        tenant=tenant,
        created_by=user,
        first_name=first,
        last_name=last,
        email=f'{first.lower()}@renewal.test',
        phone='9999999999',
    )


def _membership(tenant, branch, member, user, today, end_date, status='active'):
    """
    Create a membership with a specific end_date.

    Membership.save() recomputes end_date from plan+start_date, so we create
    with a start_date that results in a future end_date (within the DB window),
    then override end_date and status via update() to avoid re-triggering
    lifecycle logic.
    """
    plan = MembershipPlan(
        tenant=tenant,
        branch=branch,
        name=f'Plan-{uuid.uuid4().hex[:8]}',
        plan_type='DURATION',
        price=0,                      # zero-price → payment_status=paid → status=active
        billing_cycle_type='MONTHLY',
        billing_interval=1,
    )
    plan.save()

    m = Membership(
        tenant=tenant,
        branch=branch,
        member=member,
        plan=plan,
        start_date=today - timedelta(days=23),  # end_date ≈ today+7 after monthly calc
        created_by=user,
    )
    m.save()

    # Override to the exact end_date / status needed for the test scenario
    Membership._base_manager.filter(id=m.id).update(end_date=end_date, status=status)
    m.refresh_from_db()
    return m


def _log(tenant, membership, trigger_type, expiry_date):
    return RenewalTriggerLog.base_objects.create(
        tenant=tenant,
        membership=membership,
        trigger_type=trigger_type,
        expiry_date=expiry_date,
    )


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class RenewalDetectionTests(TestCase):

    TODAY = date(2026, 5, 1)  # fixed date for determinism

    def setUp(self):
        self.tenant = _tenant()
        self.branch = _branch(self.tenant)
        self.user = _user(self.tenant)
        self.member = _member(self.tenant, self.user, first='Alice', last='Test')
        self.member.branches.add(self.branch)
        self.member2 = _member(self.tenant, self.user, first='Bob', last='Other')
        self.member2.branches.add(self.branch)

    def _membership(self, end_date, status='active'):
        return _membership(
            self.tenant, self.branch, self.member,
            self.user, self.TODAY, end_date, status,
        )

    # --- stage classification -----------------------------------------------

    def test_detects_expiring_7d(self):
        self._membership(self.TODAY + timedelta(days=7))
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRING_7D)
        self.assertEqual(results[0].days_left, 7)

    def test_detects_expiring_3d(self):
        self._membership(self.TODAY + timedelta(days=3))
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRING_3D)
        self.assertEqual(results[0].days_left, 3)

    def test_detects_expiring_1d(self):
        self._membership(self.TODAY + timedelta(days=1))
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRING_1D)
        self.assertEqual(results[0].days_left, 1)

    def test_detects_expired_recovery(self):
        self._membership(self.TODAY - timedelta(days=3), status='expired')
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRED)
        self.assertEqual(results[0].days_left, -3)

    def test_expired_last_day_of_recovery_window(self):
        self._membership(self.TODAY - timedelta(days=RECOVERY_WINDOW_DAYS), status='expired')
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRED)

    def test_grace_period_membership_fires_expired_stage(self):
        # status='active' but final_end_date already passed (still within grace).
        # The expired stage must fire even though status is not 'expired'.
        self._membership(self.TODAY - timedelta(days=2), status='active')
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRED)
        self.assertEqual(results[0].days_left, -2)

    # --- boundary / skip cases -----------------------------------------------

    def test_skips_expired_outside_recovery_window(self):
        self._membership(self.TODAY - timedelta(days=RECOVERY_WINDOW_DAYS + 1), status='expired')
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(results, [])

    def test_skips_non_stage_days_left(self):
        # days_left=2 is not a valid trigger stage
        self._membership(self.TODAY + timedelta(days=2))
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(results, [])

    def test_skips_cancelled_memberships(self):
        self._membership(self.TODAY + timedelta(days=7), status='cancelled')
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(results, [])

    def test_skips_paused_memberships(self):
        self._membership(self.TODAY + timedelta(days=7), status='paused')
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(results, [])

    def test_empty_when_no_memberships(self):
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(results, [])

    # --- idempotency ---------------------------------------------------------

    def test_idempotency_skip_when_log_exists(self):
        m = self._membership(self.TODAY + timedelta(days=7))
        _log(self.tenant, m, TriggerType.EXPIRING_7D, m.final_end_date)
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(results, [])

    def test_new_cycle_triggers_when_expiry_date_changed(self):
        # Log exists for a past expiry_date (previous renewal cycle)
        m = self._membership(self.TODAY + timedelta(days=7))
        old_expiry = self.TODAY - timedelta(days=30)
        _log(self.tenant, m, TriggerType.EXPIRING_7D, old_expiry)
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRING_7D)

    def test_different_stage_not_blocked_by_existing_log(self):
        m = self._membership(self.TODAY + timedelta(days=7))
        expiry = m.final_end_date
        # Log exists for expired stage (different type), should not block expiring_7d
        _log(self.tenant, m, TriggerType.EXPIRED, expiry)
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRING_7D)

    # --- payload correctness -------------------------------------------------

    def test_payload_fields(self):
        m = self._membership(self.TODAY + timedelta(days=7))
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.membership_id, str(m.id))
        self.assertEqual(r.tenant_id, str(self.tenant.id))
        self.assertEqual(r.trigger_type, TriggerType.EXPIRING_7D)
        self.assertEqual(r.days_left, 7)
        self.assertEqual(r.member_name, 'Alice Test')
        self.assertEqual(r.phone, '9999999999')
        self.assertEqual(r.email, 'alice@renewal.test')
        self.assertEqual(r.member_id, str(self.member.id))
        self.assertEqual(r.expiry_date, self.TODAY + timedelta(days=7))

    # --- adjustments affecting final_end_date --------------------------------

    def test_extension_shifts_final_end_date(self):
        # end_date = today+3, +4-day extension → final_end_date = today+7 → expiring_7d
        m = self._membership(self.TODAY + timedelta(days=3))
        MembershipAdjustment._default_manager.create(
            tenant=self.tenant,
            membership=m,
            adjustment_type='EXTENSION',
            days=4,
            remarks='test',
            created_by=self.user,
        )
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].trigger_type, TriggerType.EXPIRING_7D)

    def test_multiple_memberships_multiple_stages(self):
        # Two different members — avoids unique_active_membership_per_branch constraint
        _membership(self.tenant, self.branch, self.member, self.user,
                    self.TODAY, self.TODAY + timedelta(days=7))
        _membership(self.tenant, self.branch, self.member2, self.user,
                    self.TODAY, self.TODAY + timedelta(days=3))
        results = RenewalDetectionService.detect_all(today=self.TODAY)
        types = {r.trigger_type for r in results}
        self.assertEqual(types, {TriggerType.EXPIRING_7D, TriggerType.EXPIRING_3D})
        self.assertEqual(len(results), 2)
