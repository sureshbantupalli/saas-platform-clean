from datetime import date
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import Tenant, Branch
from apps.authority.models import Role
from members.models import Member
from apps.memberships.models import Membership, MembershipPlan


# ============================================================
# Fixtures
# ============================================================

def make_tenant(name="TestGym"):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(" ", "-"))


def make_branch(tenant, name="Main Branch"):
    return Branch.objects.create(tenant=tenant, name=name, is_active=True)


def make_role(tenant, name="Manager"):
    return Role.objects.create(tenant=tenant, name=name)


def make_user(tenant, role, email="staff@test.com"):
    return User.objects.create_user(
        email=email,
        password="testpass123",
        tenant=tenant,
        role=role,
    )


def make_member(tenant, user, first="Alice", last="Smith", email=None):
    return Member.objects.create(
        tenant=tenant,
        created_by=user,
        first_name=first,
        last_name=last,
        email=email or f"{first.lower()}@test.com",
    )


def make_plan(tenant, branch, name="Monthly"):
    return MembershipPlan.objects.create(
        tenant=tenant,
        branch=branch,
        name=name,
        plan_type="DURATION",
        price=1000,
        billing_cycle_type="MONTHLY",
        billing_interval=1,
    )


# ============================================================
# MembershipCreateView Tests
# ============================================================

class MembershipCreateViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.tenant = make_tenant("MembershipGym")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant, "Admin")
        self.user = make_user(self.tenant, self.role, "membership@test.com")
        self.member = make_member(self.tenant, self.user, "Tester", "T", "tester@test.com")
        self.member.branches.add(self.branch)
        self.plan = make_plan(self.tenant, self.branch)
        self.client.login(email="membership@test.com", password="testpass123")

    def test_unauthenticated_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("membership_add"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_get_without_member_param_renders_member_selector(self):
        """Standalone access must show member dropdown, not crash."""
        response = self.client.get(reverse("membership_add"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select Member")

    def test_get_with_valid_member_param(self):
        url = reverse("membership_add") + f"?member={self.member.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tester")

    def test_get_with_invalid_member_param_returns_404(self):
        import uuid
        url = reverse("membership_add") + f"?member={uuid.uuid4()}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_member_returns_404(self):
        tenant2 = make_tenant("OtherGym")
        branch2 = make_branch(tenant2, "Other Branch")
        role2 = make_role(tenant2, "Staff")
        user2 = make_user(tenant2, role2, "other@test.com")
        other_member = make_member(tenant2, user2, "Spy", "S", "spy@test.com")

        url = reverse("membership_add") + f"?member={other_member.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_post_with_member_param_creates_membership(self):
        url = reverse("membership_add") + f"?member={self.member.pk}"
        response = self.client.post(url, {
            "plan": str(self.plan.pk),
            "branch": str(self.branch.pk),
            "start_date": date.today().isoformat(),
            "end_date": "",
            "status": "active",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.member.pk), response["Location"])
        self.assertTrue(Membership.objects.filter(member=self.member).exists())

    def test_post_without_member_param_creates_membership(self):
        """Standalone form must work when member is chosen via dropdown."""
        url = reverse("membership_add")
        response = self.client.post(url, {
            "member": str(self.member.pk),
            "plan": str(self.plan.pk),
            "branch": str(self.branch.pk),
            "start_date": date.today().isoformat(),
            "end_date": "",
            "status": "active",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Membership.objects.filter(member=self.member).exists())

    def test_membership_created_with_correct_tenant_and_creator(self):
        url = reverse("membership_add") + f"?member={self.member.pk}"
        self.client.post(url, {
            "plan": str(self.plan.pk),
            "branch": str(self.branch.pk),
            "start_date": date.today().isoformat(),
            "end_date": "",
            "status": "active",
        })
        membership = Membership.objects.filter(member=self.member).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.tenant, self.tenant)
        self.assertEqual(membership.created_by, self.user)

    def test_form_scopes_branches_to_tenant(self):
        """Branch dropdown must not leak other tenants' branches."""
        tenant2 = make_tenant("OtherGym2")
        make_branch(tenant2, "Cross Tenant Branch")

        response = self.client.get(reverse("membership_add"))
        self.assertNotContains(response, "Cross Tenant Branch")
        self.assertContains(response, self.branch.name)

    def test_form_scopes_plans_to_tenant(self):
        """Plan dropdown must not leak other tenants' plans."""
        tenant2 = make_tenant("OtherGym3")
        branch2 = make_branch(tenant2, "Branch 3")
        make_plan(tenant2, branch2, "Cross Tenant Plan")

        response = self.client.get(reverse("membership_add"))
        self.assertNotContains(response, "Cross Tenant Plan")


# ============================================================
# Membership Model Tests
# ============================================================

class MembershipModelTest(TestCase):

    def setUp(self):
        self.tenant = make_tenant("ModelGym")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant, "Staff")
        self.user = make_user(self.tenant, self.role, "model@test.com")
        self.member = make_member(self.tenant, self.user, "Model", "M", "model@member.com")
        self.member.branches.add(self.branch)
        self.plan = make_plan(self.tenant, self.branch)

    def test_tenant_auto_set_from_branch(self):
        m = Membership(
            member=self.member,
            branch=self.branch,
            plan=self.plan,
            start_date=date.today(),
            end_date=date.today(),
            status="active",
            created_by=self.user,
        )
        m.save()
        self.assertEqual(m.tenant, self.tenant)

    def test_plan_name_snapshot_on_save(self):
        m = Membership(
            member=self.member,
            branch=self.branch,
            plan=self.plan,
            start_date=date.today(),
            end_date=date.today(),
            status="active",
            created_by=self.user,
        )
        m.save()
        self.assertEqual(m.plan_name, self.plan.name)

    def test_end_date_auto_calculated_from_plan(self):
        """Monthly plan: end_date should be ~1 month after start_date."""
        from dateutil.relativedelta import relativedelta
        start = date.today()
        m = Membership(
            member=self.member,
            branch=self.branch,
            plan=self.plan,
            start_date=start,
            end_date=start,  # will be overridden
            status="active",
            created_by=self.user,
        )
        m.save()
        expected_end = start + relativedelta(months=1)
        self.assertEqual(m.end_date, expected_end)
