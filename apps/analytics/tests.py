"""
Analytics module tests.

Covers:
  - Summary metrics: members, leads, revenue, pending payments
  - Alert logic: follow-ups, expiring memberships, at-risk, hot leads
  - At-risk member detection
  - Retention calculation
  - Tenant isolation (another tenant's data never bleeds in)
  - API endpoint: auth, structure, tenant isolation
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Tenant, Branch
from members.models import Member
from apps.memberships.models import Membership, MembershipPlan
from apps.payments.models import Payment, PaymentGateway, PaymentStatus
from apps.attendance.models import Attendance
from crm.models import Enquiry, EnquiryActivity, FollowUp, LeadStage, EnquirySource

from apps.analytics.services.dashboard_service import (
    get_dashboard_summary,
    _at_risk_count,
    _retention,
    _summary,
    _alerts,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_world(name="AnalyticsGym", email="owner@test.com"):
    tenant = Tenant.objects.create(name=name, subdomain=name.lower().replace(" ", ""))
    branch = Branch.objects.create(tenant=tenant, name="Main", is_active=True)
    role   = Role.objects.create(tenant=tenant, name="Admin")
    user   = User.objects.create_user(email=email, password="pass123", tenant=tenant, role=role)
    return tenant, branch, user


def make_member(tenant, user, branch=None, first="Test", last="Member"):
    m = Member.objects.create(tenant=tenant, created_by=user, first_name=first, last_name=last)
    if branch:
        m.branches.add(branch)
    return m


def make_plan(tenant, branch):
    return MembershipPlan.objects.create(
        tenant=tenant, branch=branch, name="Monthly",
        plan_type="DURATION", price=Decimal("1000"),
        billing_cycle_type="MONTHLY", billing_interval=1,
    )


def make_membership(tenant, member, plan, user=None, status="active", days_from_now=30):
    today = date.today()
    member.branches.add(plan.branch)
    # Use update() path to bypass full_clean() — test data doesn't need form validation
    ms = Membership.__new__(Membership)
    Membership.base_objects.bulk_create([
        Membership(
            tenant=tenant, member=member, branch=plan.branch, plan=plan,
            plan_name=plan.name, start_date=today,
            end_date=today + timedelta(days=days_from_now),
            status=status, payment_status="paid",
            amount_paid=plan.price, fee_amount=plan.price,
            created_by=user,
        )
    ])
    return Membership.base_objects.filter(
        tenant=tenant, member=member, status=status
    ).latest("created_at")


def make_payment(tenant, user, amount, status=PaymentStatus.SUCCESS, days_ago=0):
    from django.utils import timezone as tz
    p = Payment.base_objects.create(
        tenant=tenant, amount=amount, currency="INR",
        status=status, purpose="membership",
        gateway=PaymentGateway.OFFLINE, created_by=user,
    )
    if days_ago:
        Payment.base_objects.filter(pk=p.pk).update(
            created_at=tz.now() - timedelta(days=days_ago)
        )
    return p


def make_attendance(tenant, member, user, days_ago=0, status="present"):
    session_date = date.today() - timedelta(days=days_ago)
    return Attendance.base_objects.create(
        tenant=tenant, member=member,
        attendance_type="walkin",
        session_date=session_date,
        status=status,
        marked_by=user,
    )


_enquiry_seq = 0

def make_enquiry(tenant, branch, user, converted=False, next_followup_days=None):
    global _enquiry_seq
    _enquiry_seq += 1

    src_name = f"Src{_enquiry_seq}"
    if not EnquirySource.objects.filter(tenant=tenant, name=src_name).exists():
        EnquirySource.objects.create(tenant=tenant, name=src_name)
    source = EnquirySource.objects.get(tenant=tenant, name=src_name)

    stage_name = f"Stg{_enquiry_seq}"
    if not LeadStage.objects.filter(tenant=tenant, name=stage_name).exists():
        LeadStage.objects.create(tenant=tenant, name=stage_name, stage_type="NEW")
    stage = LeadStage.objects.get(tenant=tenant, name=stage_name)

    nfd = None
    if next_followup_days is not None:
        nfd = date.today() + timedelta(days=next_followup_days)

    # Use bulk_create to bypass save() hook (avoids auto-follow-up creation noise)
    Enquiry.objects.bulk_create([
        Enquiry(
            tenant=tenant, branch=branch, full_name="Test Lead",
            phone=f"9{_enquiry_seq:09d}",   # always exactly 10 digits, unique
            source=source, current_stage=stage, created_by=user,
            next_followup_date=nfd,
        )
    ])
    enquiry = Enquiry.objects.filter(tenant=tenant).latest("id")
    if converted:
        member = make_member(tenant, user, first="Converted")
        Enquiry.objects.filter(pk=enquiry.pk).update(converted_member=member)
    return Enquiry.objects.get(pk=enquiry.pk)


def make_followup(tenant, user, enquiry, days_ago=0, status=FollowUp.STATUS_PENDING):
    due = date.today() - timedelta(days=days_ago)
    return FollowUp.objects.create(
        tenant=tenant, enquiry=enquiry, followup_type=FollowUp.TYPE_CALL,
        due_date=due, status=status, created_by=user,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Summary Metrics
# ══════════════════════════════════════════════════════════════════════════════

class SummaryMetricsTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world()
        self.plan = make_plan(self.tenant, self.branch)

    def test_total_members_count(self):
        make_member(self.tenant, self.user, first="Alice")
        make_member(self.tenant, self.user, first="Bob")
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["summary"]["total_members"], 2)

    def test_soft_deleted_members_excluded(self):
        m = make_member(self.tenant, self.user)
        Member.objects.filter(pk=m.pk).update(is_deleted=True)
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["summary"]["total_members"], 0)

    def test_active_members_counts_active_memberships_only(self):
        m1 = make_member(self.tenant, self.user, first="Active")
        m2 = make_member(self.tenant, self.user, first="Expired")
        make_membership(self.tenant, m1, self.plan, status="active")
        make_membership(self.tenant, m2, self.plan, status="expired")
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["summary"]["active_members"], 1)

    def test_new_members_last_30_days(self):
        make_member(self.tenant, self.user, first="New")
        m_old = make_member(self.tenant, self.user, first="Old")
        Member.objects.filter(pk=m_old.pk).update(
            created_at=timezone.now() - timedelta(days=45)
        )
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["summary"]["new_members_last_30_days"], 1)

    def test_conversion_rate_calculated(self):
        make_enquiry(self.tenant, self.branch, self.user, converted=True)
        make_enquiry(self.tenant, self.branch, self.user, converted=False)
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["summary"]["total_leads"], 2)
        self.assertEqual(data["summary"]["converted_leads"], 1)
        self.assertEqual(data["summary"]["conversion_rate"], 50.0)

    def test_conversion_rate_zero_when_no_leads(self):
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["summary"]["conversion_rate"], 0.0)

    def test_revenue_mtd_sums_success_payments_this_month(self):
        make_payment(self.tenant, self.user, Decimal("1000"), PaymentStatus.SUCCESS)
        make_payment(self.tenant, self.user, Decimal("2000"), PaymentStatus.SUCCESS)
        make_payment(self.tenant, self.user, Decimal("500"),  PaymentStatus.FAILED)
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(Decimal(data["summary"]["revenue_mtd"]), Decimal("3000"))

    def test_pending_payments_count_and_amount(self):
        make_payment(self.tenant, self.user, Decimal("800"), PaymentStatus.PENDING)
        make_payment(self.tenant, self.user, Decimal("400"), PaymentStatus.CREATED)
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["summary"]["pending_payments_count"], 2)
        self.assertEqual(Decimal(data["summary"]["pending_payments_amount"]), Decimal("1200"))


# ══════════════════════════════════════════════════════════════════════════════
# 2. Alert Logic
# ══════════════════════════════════════════════════════════════════════════════

class AlertLogicTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("AlertGym", "alert@test.com")
        self.plan = make_plan(self.tenant, self.branch)

    def _alert_types(self, data):
        return [a["type"] for a in data["alerts"]]

    def test_no_alerts_when_everything_clean(self):
        data = get_dashboard_summary(self.tenant)
        self.assertEqual(data["alerts"], [])

    def test_followup_due_today_alert(self):
        enq = make_enquiry(self.tenant, self.branch, self.user)
        make_followup(self.tenant, self.user, enq, days_ago=0)  # due today
        data = get_dashboard_summary(self.tenant)
        self.assertIn("followup_due_today", self._alert_types(data))
        alert = next(a for a in data["alerts"] if a["type"] == "followup_due_today")
        self.assertEqual(alert["count"], 1)

    def test_overdue_followup_alert(self):
        enq = make_enquiry(self.tenant, self.branch, self.user)
        make_followup(self.tenant, self.user, enq, days_ago=3)  # overdue
        data = get_dashboard_summary(self.tenant)
        self.assertIn("followup_overdue", self._alert_types(data))

    def test_membership_expiring_alert(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active", days_from_now=5)
        data = get_dashboard_summary(self.tenant)
        self.assertIn("membership_expiring", self._alert_types(data))

    def test_membership_not_expiring_beyond_7_days(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active", days_from_now=30)
        data = get_dashboard_summary(self.tenant)
        self.assertNotIn("membership_expiring", self._alert_types(data))

    def test_at_risk_alert_appears_when_member_not_attended(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active")
        # No attendance record → at-risk
        data = get_dashboard_summary(self.tenant)
        self.assertIn("at_risk_members", self._alert_types(data))

    def test_at_risk_alert_absent_when_attended_recently(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active")
        make_attendance(self.tenant, m, self.user, days_ago=2)
        data = get_dashboard_summary(self.tenant)
        self.assertNotIn("at_risk_members", self._alert_types(data))

    def test_hot_lead_alert(self):
        enq = make_enquiry(self.tenant, self.branch, self.user, next_followup_days=-1)
        data = get_dashboard_summary(self.tenant)
        self.assertIn("hot_leads_not_contacted", self._alert_types(data))

    def test_hot_lead_no_alert_when_contacted_recently(self):
        enq = make_enquiry(self.tenant, self.branch, self.user, next_followup_days=-1)
        EnquiryActivity.objects.create(
            tenant=self.tenant, enquiry=enq,
            action_type="CALL_LOGGED", performed_by=self.user,
        )
        data = get_dashboard_summary(self.tenant)
        self.assertNotIn("hot_leads_not_contacted", self._alert_types(data))


# ══════════════════════════════════════════════════════════════════════════════
# 3. At-Risk Member Detection
# ══════════════════════════════════════════════════════════════════════════════

class AtRiskDetectionTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("RiskGym", "risk@test.com")
        self.plan = make_plan(self.tenant, self.branch)
        from apps.attendance.models import Attendance as A
        from apps.memberships.models import Membership as M
        self.Attendance = A
        self.Membership = M

    def test_member_with_no_attendance_is_at_risk(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active")
        count = _at_risk_count(
            self.tenant, date.today() - timedelta(days=7),
            self.Membership, self.Attendance
        )
        self.assertEqual(count, 1)

    def test_member_attended_6_days_ago_is_not_at_risk(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active")
        make_attendance(self.tenant, m, self.user, days_ago=6)
        count = _at_risk_count(
            self.tenant, date.today() - timedelta(days=7),
            self.Membership, self.Attendance
        )
        self.assertEqual(count, 0)

    def test_member_attended_8_days_ago_is_at_risk(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active")
        make_attendance(self.tenant, m, self.user, days_ago=8)
        count = _at_risk_count(
            self.tenant, date.today() - timedelta(days=7),
            self.Membership, self.Attendance
        )
        self.assertEqual(count, 1)

    def test_expired_membership_member_not_counted_as_at_risk(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="expired")
        count = _at_risk_count(
            self.tenant, date.today() - timedelta(days=7),
            self.Membership, self.Attendance
        )
        self.assertEqual(count, 0)

    def test_multiple_at_risk_counted_correctly(self):
        for i in range(3):
            m = make_member(self.tenant, self.user, first=f"Risk{i}")
            make_membership(self.tenant, m, self.plan, status="active")
        count = _at_risk_count(
            self.tenant, date.today() - timedelta(days=7),
            self.Membership, self.Attendance
        )
        self.assertEqual(count, 3)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Retention Calculation
# ══════════════════════════════════════════════════════════════════════════════

class RetentionTests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("RetGym", "ret@test.com")
        self.plan = make_plan(self.tenant, self.branch)
        from apps.memberships.models import Membership as M
        self.Membership = M

    def test_retention_rate_100_when_no_churn(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active")
        result = _retention(self.tenant, timezone.now() - timedelta(days=30), self.Membership)
        self.assertEqual(result["retention_rate"], 100.0)
        self.assertEqual(result["churned_last_30_days"], 0)

    def test_retention_rate_calculated_with_churn(self):
        m1 = make_member(self.tenant, self.user, first="Active")
        m2 = make_member(self.tenant, self.user, first="Churned")
        make_membership(self.tenant, m1, self.plan, status="active")
        ms = make_membership(self.tenant, m2, self.plan, status="cancelled")
        # Move updated_at to within last 30 days
        Membership.base_objects.filter(pk=ms.pk).update(
            updated_at=timezone.now() - timedelta(days=5)
        )
        result = _retention(self.tenant, timezone.now() - timedelta(days=30), self.Membership)
        self.assertEqual(result["active_members"],       1)
        self.assertEqual(result["churned_last_30_days"], 1)
        self.assertEqual(result["retention_rate"],       50.0)

    def test_avg_membership_duration_computed(self):
        m = make_member(self.tenant, self.user)
        make_membership(self.tenant, m, self.plan, status="active", days_from_now=30)
        result = _retention(self.tenant, timezone.now() - timedelta(days=30), self.Membership)
        self.assertGreaterEqual(result["avg_membership_duration_days"], 30)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Tenant Isolation
# ══════════════════════════════════════════════════════════════════════════════

class TenantIsolationTests(TestCase):

    def setUp(self):
        self.t1, self.b1, self.u1 = make_world("Gym1", "g1@test.com")
        self.t2, self.b2, self.u2 = make_world("Gym2", "g2@test.com")
        self.plan1 = make_plan(self.t1, self.b1)
        self.plan2 = make_plan(self.t2, self.b2)

    def test_member_count_isolated_per_tenant(self):
        make_member(self.t1, self.u1)
        make_member(self.t1, self.u1)
        make_member(self.t2, self.u2)  # different tenant

        d1 = get_dashboard_summary(self.t1)
        d2 = get_dashboard_summary(self.t2)

        self.assertEqual(d1["summary"]["total_members"], 2)
        self.assertEqual(d2["summary"]["total_members"], 1)

    def test_revenue_isolated_per_tenant(self):
        make_payment(self.t1, self.u1, Decimal("5000"), PaymentStatus.SUCCESS)
        make_payment(self.t2, self.u2, Decimal("1000"), PaymentStatus.SUCCESS)

        d1 = get_dashboard_summary(self.t1)
        d2 = get_dashboard_summary(self.t2)

        self.assertEqual(Decimal(d1["summary"]["revenue_mtd"]), Decimal("5000"))
        self.assertEqual(Decimal(d2["summary"]["revenue_mtd"]), Decimal("1000"))

    def test_at_risk_isolated_per_tenant(self):
        m1 = make_member(self.t1, self.u1)
        make_membership(self.t1, m1, self.plan1, status="active")
        # No attendance → t1 has 1 at-risk member; t2 has 0

        d1 = get_dashboard_summary(self.t1)
        d2 = get_dashboard_summary(self.t2)

        self.assertEqual(d1["at_risk_members"]["count"], 1)
        self.assertEqual(d2["at_risk_members"]["count"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# 6. API Endpoint
# ══════════════════════════════════════════════════════════════════════════════

class AnalyticsDashboardAPITests(TestCase):

    def setUp(self):
        self.tenant, self.branch, self.user = make_world("APIGym", "api@test.com")
        self.client = Client()

    def test_unauthenticated_returns_401_or_403(self):
        resp = self.client.get("/api/analytics/dashboard/")
        self.assertIn(resp.status_code, [401, 403])

    def test_authenticated_returns_200(self):
        self.client.login(username="api@test.com", password="pass123")
        resp = self.client.get("/api/analytics/dashboard/")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_required_keys(self):
        self.client.login(username="api@test.com", password="pass123")
        resp = self.client.get("/api/analytics/dashboard/")
        data = resp.json()
        for key in ("summary", "alerts", "charts", "attendance", "retention",
                    "peak_hours", "at_risk_members", "engagement"):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_summary_has_required_fields(self):
        self.client.login(username="api@test.com", password="pass123")
        resp = self.client.get("/api/analytics/dashboard/")
        summary = resp.json()["summary"]
        for field in ("total_members", "active_members", "new_members_last_30_days",
                      "total_leads", "conversion_rate", "revenue_mtd",
                      "pending_payments_count", "pending_payments_amount"):
            self.assertIn(field, summary, f"Missing summary field: {field}")

    def test_charts_has_required_keys(self):
        self.client.login(username="api@test.com", password="pass123")
        resp = self.client.get("/api/analytics/dashboard/")
        charts = resp.json()["charts"]
        for key in ("revenue_trend", "lead_funnel", "attendance_trend"):
            self.assertIn(key, charts, f"Missing chart key: {key}")

    def test_alerts_is_list(self):
        self.client.login(username="api@test.com", password="pass123")
        resp = self.client.get("/api/analytics/dashboard/")
        self.assertIsInstance(resp.json()["alerts"], list)

    def test_tenant_isolation_via_api(self):
        """A second tenant's data must not appear in the first tenant's API response."""
        t2, b2, u2 = make_world("OtherGym", "other@test.com")
        plan2 = make_plan(t2, b2)
        for i in range(5):
            m = make_member(t2, u2, first=f"Other{i}")
        make_payment(t2, u2, Decimal("99999"), PaymentStatus.SUCCESS)

        self.client.login(username="api@test.com", password="pass123")
        resp = self.client.get("/api/analytics/dashboard/")
        data = resp.json()

        self.assertEqual(data["summary"]["total_members"], 0)
        self.assertEqual(Decimal(data["summary"]["revenue_mtd"]), Decimal("0"))
