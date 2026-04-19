import uuid
from datetime import date, timedelta, time

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.actions.services.next_best_action_service import get_next_actions

User = get_user_model()

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_world(name="TestGym"):
    from apps.core.models import Tenant, Branch
    from apps.authority.models import Role
    slug = uuid.uuid4().hex[:8]
    tenant = Tenant.objects.create(name=name, subdomain=slug)
    branch = Branch.objects.create(tenant=tenant, name="Main Branch", is_active=True)
    role   = Role.objects.create(tenant=tenant, name="Admin")
    user   = User.objects.create_user(
        email=f"owner-{slug}@test.com", password="pw", tenant=tenant, role=role
    )
    return tenant, branch, user


def make_member(tenant, branch, user=None):
    from members.models import Member
    m = Member.objects.create(
        tenant=tenant,
        created_by=user,
        first_name="Test",
        last_name="Member",
    )
    m.branches.add(branch)
    return m


def make_plan(tenant, branch):
    from apps.memberships.models import MembershipPlan
    from decimal import Decimal
    return MembershipPlan.objects.create(
        tenant=tenant,
        branch=branch,
        name=f"Plan-{uuid.uuid4().hex[:4]}",
        plan_type="DURATION",
        billing_cycle_type="MONTHLY",
        billing_interval=1,
        price=Decimal("1000"),
    )


def make_membership(tenant, member, plan, branch, status="active",
                    payment_status="paid", end_date=None):
    from apps.memberships.models import Membership
    today = date.today()
    end_date = end_date or (today + timedelta(days=30))
    Membership.base_objects.bulk_create([
        Membership(
            tenant=tenant,
            member=member,
            branch=branch,
            plan=plan,
            plan_name=plan.name,
            start_date=today,
            end_date=end_date,
            status=status,
            payment_status=payment_status,
            fee_amount=1000,
        )
    ])
    return Membership.base_objects.filter(
        tenant=tenant, member=member
    ).latest("created_at")


def make_attendance(tenant, member, branch, session_date, status="present"):
    from apps.attendance.models import Attendance
    Attendance.base_objects.bulk_create([
        Attendance(
            tenant=tenant,
            member=member,
            attendance_type="walkin",
            session_date=session_date,
            status=status,
        )
    ])


def make_followup(tenant, branch, user, due_date, status="pending"):
    from crm.models import FollowUp
    FollowUp.objects.create(
        tenant=tenant,
        due_date=due_date,
        status=status,
        followup_type=FollowUp.TYPE_CALL,
        notes="test",
        created_by=user,
    )


def make_enquiry(tenant, branch, user, next_followup_date=None, converted=False):
    from crm.models import Enquiry
    seq = uuid.uuid4().int % 10**9
    enquiry = Enquiry.objects.create(
        tenant=tenant,
        branch=branch,
        full_name=f"Lead {seq}",
        phone=f"9{seq:09d}",
        next_followup_date=next_followup_date,
        created_by=user,
    )
    return enquiry


def make_enquiry_activity(tenant, enquiry, user, days_ago=0):
    from crm.models import EnquiryActivity
    from django.utils import timezone
    activity = EnquiryActivity(
        tenant=tenant,
        enquiry=enquiry,
        action_type="CALL_LOGGED",
        performed_by=user,
    )
    activity.save()
    if days_ago:
        EnquiryActivity.objects.filter(pk=activity.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
    return activity


def make_session_instance(tenant, branch, session_date, capacity=10):
    from apps.sessions.models import SessionType, SessionTemplate, SessionSchedule, SessionInstance
    import datetime

    stype = SessionType.objects.create(name=f"Type-{uuid.uuid4().hex[:4]}")
    template = SessionTemplate.base_objects.create(
        tenant=tenant,
        session_type=stype,
        name=f"Tpl-{uuid.uuid4().hex[:4]}",
        duration_minutes=60,
        capacity=capacity,
    )
    # Use the actual day-of-week so the signal generates an instance for session_date
    schedule = SessionSchedule.base_objects.create(
        tenant=tenant,
        template=template,
        day_of_week=session_date.isoweekday(),
        start_time=datetime.time(9, 0),
        start_date=session_date,
    )
    # Signal auto-creates the SessionInstance; retrieve it
    instance = SessionInstance.base_objects.filter(
        schedule=schedule, session_date=session_date
    ).first()
    if instance is None:
        instance, _ = SessionInstance.base_objects.get_or_create(
            tenant=tenant,
            schedule=schedule,
            session_date=session_date,
            start_time=datetime.time(9, 0),
            defaults={"capacity": capacity, "status": SessionInstance.STATUS_SCHEDULED},
        )
    return instance


def make_booking(tenant, session_instance, member, status="booked"):
    from apps.sessions.models import Booking
    return Booking.base_objects.create(
        tenant=tenant,
        session_instance=session_instance,
        member=member,
        status=status,
    )


# ── Test classes ──────────────────────────────────────────────────────────────

class FollowupOverdueTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym1")

    def test_overdue_followup_detected(self):
        make_followup(self.tenant, self.branch, self.user,
                      due_date=date.today() - timedelta(days=1))
        actions = get_next_actions(self.tenant)
        types = [a["type"] for a in actions]
        self.assertIn("followup_overdue", types)
        action = next(a for a in actions if a["type"] == "followup_overdue")
        self.assertEqual(action["count"], 1)
        self.assertEqual(action["priority"], "HIGH")

    def test_future_followup_not_counted(self):
        make_followup(self.tenant, self.branch, self.user,
                      due_date=date.today() + timedelta(days=1))
        actions = get_next_actions(self.tenant)
        types = [a["type"] for a in actions]
        self.assertNotIn("followup_overdue", types)

    def test_done_followup_not_counted(self):
        make_followup(self.tenant, self.branch, self.user,
                      due_date=date.today() - timedelta(days=1), status="done")
        actions = get_next_actions(self.tenant)
        types = [a["type"] for a in actions]
        self.assertNotIn("followup_overdue", types)

    def test_count_aggregates_multiple(self):
        for i in range(3):
            make_followup(self.tenant, self.branch, self.user,
                          due_date=date.today() - timedelta(days=i + 1))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "followup_overdue"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 3)


class HotLeadsNotContactedTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym2")

    def test_overdue_followup_no_activity_detected(self):
        make_enquiry(self.tenant, self.branch, self.user,
                     next_followup_date=date.today() - timedelta(days=3))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "hot_leads_not_contacted"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)
        self.assertEqual(action["priority"], "HIGH")

    def test_recent_activity_suppresses_lead(self):
        enquiry = make_enquiry(self.tenant, self.branch, self.user,
                               next_followup_date=date.today() - timedelta(days=3))
        make_enquiry_activity(self.tenant, enquiry, self.user, days_ago=0)
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "hot_leads_not_contacted"), None)
        self.assertIsNone(action)

    def test_old_activity_does_not_suppress(self):
        enquiry = make_enquiry(self.tenant, self.branch, self.user,
                               next_followup_date=date.today() - timedelta(days=5))
        make_enquiry_activity(self.tenant, enquiry, self.user, days_ago=3)
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "hot_leads_not_contacted"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)

    def test_converted_lead_excluded(self):
        from members.models import Member
        enquiry = make_enquiry(self.tenant, self.branch, self.user,
                               next_followup_date=date.today() - timedelta(days=3))
        member = make_member(self.tenant, self.branch, self.user)
        enquiry.converted_member = member
        enquiry.save()
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "hot_leads_not_contacted"), None)
        self.assertIsNone(action)

    def test_future_followup_date_not_counted(self):
        make_enquiry(self.tenant, self.branch, self.user,
                     next_followup_date=date.today() + timedelta(days=2))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "hot_leads_not_contacted"), None)
        self.assertIsNone(action)


class FollowupDueTodayTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym3")

    def test_due_today_detected(self):
        make_followup(self.tenant, self.branch, self.user, due_date=date.today())
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "followup_due_today"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)
        self.assertEqual(action["priority"], "MEDIUM")

    def test_overdue_not_counted_as_due_today(self):
        make_followup(self.tenant, self.branch, self.user,
                      due_date=date.today() - timedelta(days=1))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "followup_due_today"), None)
        self.assertIsNone(action)


class ExpiringMembershipsTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym4")
        self.plan = make_plan(self.tenant, self.branch)

    def test_expiring_within_7_days_detected(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        end_date=date.today() + timedelta(days=5))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "expiring_memberships"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)
        self.assertEqual(action["priority"], "HIGH")

    def test_expiring_beyond_7_days_not_counted(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        end_date=date.today() + timedelta(days=10))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "expiring_memberships"), None)
        self.assertIsNone(action)

    def test_expired_membership_not_counted(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        status="expired",
                        end_date=date.today() - timedelta(days=1))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "expiring_memberships"), None)
        self.assertIsNone(action)


class AtRiskMembersTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym5")
        self.plan = make_plan(self.tenant, self.branch)

    def test_member_with_no_attendance_is_at_risk(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)
        self.assertEqual(action["priority"], "HIGH")

    def test_member_attended_recently_is_not_at_risk(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        make_attendance(self.tenant, member, self.branch,
                        session_date=date.today() - timedelta(days=2))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNone(action)

    def test_member_attended_8_days_ago_is_at_risk(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        make_attendance(self.tenant, member, self.branch,
                        session_date=date.today() - timedelta(days=8))
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)

    def test_inactive_membership_not_counted(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch, status="expired")
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNone(action)


class LowUtilizationSlotsTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym6")

    def test_empty_session_is_low_utilization(self):
        today = date.today()
        make_session_instance(self.tenant, self.branch,
                              session_date=today + timedelta(days=1), capacity=10)
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "low_utilization_slots"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)
        self.assertEqual(action["priority"], "MEDIUM")

    def test_well_booked_session_not_flagged(self):
        today = date.today()
        instance = make_session_instance(self.tenant, self.branch,
                                         session_date=today + timedelta(days=1), capacity=10)
        for _ in range(4):
            member = make_member(self.tenant, self.branch, self.user)
            make_booking(self.tenant, instance, member)
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "low_utilization_slots"), None)
        self.assertIsNone(action)

    def test_session_beyond_7_days_not_counted(self):
        today = date.today()
        make_session_instance(self.tenant, self.branch,
                              session_date=today + timedelta(days=9), capacity=10)
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "low_utilization_slots"), None)
        self.assertIsNone(action)

    def test_cancelled_session_not_counted(self):
        from apps.sessions.models import SessionInstance
        today = date.today()
        instance = make_session_instance(self.tenant, self.branch,
                                         session_date=today + timedelta(days=1), capacity=10)
        SessionInstance.base_objects.filter(pk=instance.pk).update(
            status=SessionInstance.STATUS_CANCELLED
        )
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "low_utilization_slots"), None)
        self.assertIsNone(action)


class PaymentPendingTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym7")
        self.plan = make_plan(self.tenant, self.branch)

    def test_unpaid_active_membership_flagged(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        payment_status="unpaid")
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "payment_pending"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["count"], 1)
        self.assertEqual(action["priority"], "HIGH")

    def test_partial_payment_flagged(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        payment_status="partial")
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "payment_pending"), None)
        self.assertIsNotNone(action)

    def test_paid_membership_not_flagged(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        payment_status="paid")
        actions = get_next_actions(self.tenant)
        action = next((a for a in actions if a["type"] == "payment_pending"), None)
        self.assertIsNone(action)


class PriorityOrderingTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("Gym8")
        self.plan = make_plan(self.tenant, self.branch)

    def test_high_before_medium(self):
        # HIGH: unpaid membership
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        payment_status="unpaid")
        # MEDIUM: followup due today
        make_followup(self.tenant, self.branch, self.user, due_date=date.today())
        actions = get_next_actions(self.tenant)
        priorities = [a["priority"] for a in actions]
        high_idx  = next(i for i, p in enumerate(priorities) if p == "HIGH")
        medium_idx = next(i for i, p in enumerate(priorities) if p == "MEDIUM")
        self.assertLess(high_idx, medium_idx)

    def test_among_high_larger_count_first(self):
        # 3 overdue followups (HIGH)
        for i in range(3):
            make_followup(self.tenant, self.branch, self.user,
                          due_date=date.today() - timedelta(days=i + 1))
        # 1 unpaid membership (HIGH)
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        payment_status="unpaid")
        actions = get_next_actions(self.tenant)
        high_actions = [a for a in actions if a["priority"] == "HIGH"]
        self.assertGreater(len(high_actions), 1)
        self.assertGreaterEqual(high_actions[0]["count"], high_actions[1]["count"])

    def test_zero_count_actions_excluded(self):
        actions = get_next_actions(self.tenant)
        self.assertEqual(actions, [])

    def test_action_response_has_required_fields(self):
        make_followup(self.tenant, self.branch, self.user,
                      due_date=date.today() - timedelta(days=1))
        actions = get_next_actions(self.tenant)
        self.assertTrue(len(actions) > 0)
        required = {"type", "priority", "title", "count",
                    "cta_url", "cta_label", "urgency", "quick_actions", "description"}
        for action in actions:
            for field in required:
                self.assertIn(field, action, f"Missing field '{field}' in action {action['type']}")


class TenantIsolationTests(TestCase):

    def setUp(self):
        self.t1, self.b1, self.u1 = make_world("TenantA")
        self.t2, self.b2, self.u2 = make_world("TenantB")

    def test_followup_isolated_by_tenant(self):
        # Only t2 has an overdue followup
        make_followup(self.t2, self.b2, self.u2,
                      due_date=date.today() - timedelta(days=1))
        actions = get_next_actions(self.t1)
        action = next((a for a in actions if a["type"] == "followup_overdue"), None)
        self.assertIsNone(action)

    def test_membership_isolated_by_tenant(self):
        plan2 = make_plan(self.t2, self.b2)
        member2 = make_member(self.t2, self.b2, self.u2)
        make_membership(self.t2, member2, plan2, self.b2,
                        end_date=date.today() + timedelta(days=3))
        actions = get_next_actions(self.t1)
        action = next((a for a in actions if a["type"] == "expiring_memberships"), None)
        self.assertIsNone(action)

    def test_hot_leads_isolated_by_tenant(self):
        make_enquiry(self.t2, self.b2, self.u2,
                     next_followup_date=date.today() - timedelta(days=3))
        actions = get_next_actions(self.t1)
        action = next((a for a in actions if a["type"] == "hot_leads_not_contacted"), None)
        self.assertIsNone(action)

    def test_at_risk_isolated_by_tenant(self):
        plan2 = make_plan(self.t2, self.b2)
        member2 = make_member(self.t2, self.b2, self.u2)
        make_membership(self.t2, member2, plan2, self.b2)
        actions = get_next_actions(self.t1)
        action = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNone(action)


class CTAMappingTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("CTAGym")
        self.plan = make_plan(self.tenant, self.branch)

    def _get_action(self, action_type):
        return next((a for a in get_next_actions(self.tenant) if a["type"] == action_type), None)

    def test_followup_overdue_cta(self):
        make_followup(self.tenant, self.branch, self.user,
                      due_date=date.today() - timedelta(days=1))
        a = self._get_action("followup_overdue")
        self.assertIsNotNone(a)
        self.assertEqual(a["cta_url"], "/crm/followups/")
        self.assertIsInstance(a["cta_label"], str)

    def test_followup_due_today_cta(self):
        make_followup(self.tenant, self.branch, self.user, due_date=date.today())
        a = self._get_action("followup_due_today")
        self.assertIsNotNone(a)
        self.assertEqual(a["cta_url"], "/crm/followups/")

    def test_hot_leads_cta(self):
        make_enquiry(self.tenant, self.branch, self.user,
                     next_followup_date=date.today() - timedelta(days=3))
        a = self._get_action("hot_leads_not_contacted")
        self.assertIsNotNone(a)
        self.assertEqual(a["cta_url"], "/crm/dashboard/")

    def test_expiring_memberships_cta(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        end_date=date.today() + timedelta(days=5))
        a = self._get_action("expiring_memberships")
        self.assertIsNotNone(a)
        self.assertIn("/members/", a["cta_url"])

    def test_at_risk_members_cta(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        a = self._get_action("at_risk_members")
        self.assertIsNotNone(a)
        self.assertIn("/members/", a["cta_url"])

    def test_payment_pending_cta(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        payment_status="unpaid")
        a = self._get_action("payment_pending")
        self.assertIsNotNone(a)
        self.assertIn("/payments/", a["cta_url"])

    def test_low_utilization_cta(self):
        make_session_instance(self.tenant, self.branch,
                              session_date=date.today() + timedelta(days=1))
        a = self._get_action("low_utilization_slots")
        self.assertIsNotNone(a)
        self.assertIn("/sessions/", a["cta_url"])


class UrgencyTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("UrgencyGym")
        self.plan = make_plan(self.tenant, self.branch)

    def test_overdue_urgency_mentions_days(self):
        make_followup(self.tenant, self.branch, self.user,
                      due_date=date.today() - timedelta(days=3))
        a = next(a for a in get_next_actions(self.tenant) if a["type"] == "followup_overdue")
        self.assertIn("3", a["urgency"])

    def test_expiring_urgency_mentions_days(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        end_date=date.today() + timedelta(days=2))
        a = next(a for a in get_next_actions(self.tenant) if a["type"] == "expiring_memberships")
        self.assertIn("2", a["urgency"])

    def test_due_today_urgency(self):
        make_followup(self.tenant, self.branch, self.user, due_date=date.today())
        a = next(a for a in get_next_actions(self.tenant) if a["type"] == "followup_due_today")
        self.assertIn("today", a["urgency"].lower())

    def test_hot_leads_urgency(self):
        make_enquiry(self.tenant, self.branch, self.user,
                     next_followup_date=date.today() - timedelta(days=3))
        a = next(a for a in get_next_actions(self.tenant) if a["type"] == "hot_leads_not_contacted")
        self.assertIn("2", a["urgency"])

    def test_at_risk_urgency(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        a = next(a for a in get_next_actions(self.tenant) if a["type"] == "at_risk_members")
        self.assertIn("7", a["urgency"])

    def test_payment_pending_urgency(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch,
                        payment_status="unpaid")
        a = next(a for a in get_next_actions(self.tenant) if a["type"] == "payment_pending")
        self.assertIsInstance(a["urgency"], str)
        self.assertGreater(len(a["urgency"]), 0)


class AtRiskImprovedLogicTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("AtRiskImproved")
        self.plan = make_plan(self.tenant, self.branch)

    def test_no_attendance_is_at_risk(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        actions = get_next_actions(self.tenant)
        a = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNotNone(a)
        self.assertEqual(a["count"], 1)

    def test_attendance_drop_50pct_is_at_risk(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        today = date.today()
        # Previous period: 4 sessions (days 8-14 ago)
        for i in range(8, 12):
            make_attendance(self.tenant, member, self.branch,
                            session_date=today - timedelta(days=i))
        # Recent period: 1 session (last 7 days) — 75% drop
        make_attendance(self.tenant, member, self.branch,
                        session_date=today - timedelta(days=2))
        actions = get_next_actions(self.tenant)
        a = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNotNone(a)
        self.assertEqual(a["count"], 1)

    def test_no_drop_not_at_risk(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        today = date.today()
        # Equal attendance in both periods
        for i in range(8, 11):
            make_attendance(self.tenant, member, self.branch,
                            session_date=today - timedelta(days=i))
        for i in range(1, 4):
            make_attendance(self.tenant, member, self.branch,
                            session_date=today - timedelta(days=i))
        actions = get_next_actions(self.tenant)
        a = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNone(a)

    def test_first_time_attendee_not_at_risk(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        today = date.today()
        # Attended recently but never in prev period (new member)
        make_attendance(self.tenant, member, self.branch,
                        session_date=today - timedelta(days=1))
        actions = get_next_actions(self.tenant)
        a = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNone(a)

    def test_quick_actions_structure(self):
        member = make_member(self.tenant, self.branch, self.user)
        make_membership(self.tenant, member, self.plan, self.branch)
        actions = get_next_actions(self.tenant)
        a = next((a for a in actions if a["type"] == "at_risk_members"), None)
        self.assertIsNotNone(a)
        self.assertIsInstance(a["quick_actions"], list)
        for qa in a["quick_actions"]:
            self.assertIn("type",  qa)
            self.assertIn("label", qa)
