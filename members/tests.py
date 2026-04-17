from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import Tenant, Branch
from apps.authority.models import Role, RolePermission, PermissionAction
from members.models import Member
from members.services.member_service import MemberService
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


def make_permission(module, action):
    action_obj, _ = PermissionAction.objects.get_or_create(module=module, action=action)
    return action_obj


def grant_permission(role, permission_action, tenant, scope="ANY"):
    return RolePermission.objects.create(
        role=role,
        permission_action=permission_action,
        tenant=tenant,
        scope=scope,
        is_allowed=True,
    )


# ============================================================
# MemberService Tests
# ============================================================

class MemberServiceQuerysetTest(TestCase):

    def setUp(self):
        self.tenant = make_tenant("Gym A")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant)
        self.user1 = make_user(self.tenant, self.role, "staff1@test.com")
        self.user2 = make_user(self.tenant, self.role, "staff2@test.com")

        self.m1 = make_member(self.tenant, self.user1, "Alice", "A", "alice@test.com")
        self.m2 = make_member(self.tenant, self.user1, "Bob", "B", "bob@test.com")
        self.m3 = make_member(self.tenant, self.user2, "Charlie", "C", "charlie@test.com")

    def test_all_tenant_members_visible_to_any_staff(self):
        """Staff must see all members in tenant, not just ones they created."""
        members = MemberService.get_queryset(self.user1)
        self.assertEqual(len(members), 3)

    def test_staff2_sees_members_created_by_staff1(self):
        members = MemberService.get_queryset(self.user2)
        emails = {m.email for m in members}
        self.assertIn("alice@test.com", emails)
        self.assertIn("charlie@test.com", emails)

    def test_cross_tenant_isolation(self):
        tenant2 = make_tenant("Gym B")
        branch2 = make_branch(tenant2, "Branch B")
        role2 = make_role(tenant2, "Admin")
        user2 = make_user(tenant2, role2, "admin2@test.com")
        make_member(tenant2, user2, "Dave", "D", "dave@test.com")

        members_a = MemberService.get_queryset(self.user1)
        member_emails = {m.email for m in members_a}
        self.assertNotIn("dave@test.com", member_emails)

    def test_search_by_name(self):
        members = MemberService.get_queryset(self.user1, search_query="Alice")
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].first_name, "Alice")

    def test_search_by_email(self):
        members = MemberService.get_queryset(self.user1, search_query="bob@test.com")
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].email, "bob@test.com")

    def test_search_no_results(self):
        members = MemberService.get_queryset(self.user1, search_query="zzznobody")
        self.assertEqual(len(members), 0)

    def test_soft_deleted_members_excluded(self):
        self.m1.is_deleted = True
        self.m1.save()
        members = MemberService.get_queryset(self.user1)
        emails = {m.email for m in members}
        self.assertNotIn("alice@test.com", emails)
        self.assertEqual(len(members), 2)

    def test_display_status_attached(self):
        members = MemberService.get_queryset(self.user1)
        for m in members:
            self.assertTrue(hasattr(m, "display_status"))
            self.assertEqual(m.display_status, "NO_PLAN")


class MemberServiceGetByIdTest(TestCase):

    def setUp(self):
        self.tenant = make_tenant("Gym C")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant)
        self.user1 = make_user(self.tenant, self.role, "u1@test.com")
        self.user2 = make_user(self.tenant, self.role, "u2@test.com")
        self.member = make_member(self.tenant, self.user1, "Zara", "Z", "zara@test.com")

    def test_any_staff_can_get_member_by_id(self):
        """User2 who didn't create the member should still retrieve it."""
        result = MemberService.get_by_id(self.user2, self.member.pk)
        self.assertIsNotNone(result)
        self.assertEqual(result.email, "zara@test.com")

    def test_returns_none_for_wrong_tenant(self):
        tenant2 = make_tenant("Gym D")
        role2 = make_role(tenant2, "Staff")
        user_t2 = make_user(tenant2, role2, "other@test.com")
        result = MemberService.get_by_id(user_t2, self.member.pk)
        self.assertIsNone(result)

    def test_returns_none_for_deleted_member(self):
        self.member.is_deleted = True
        self.member.save()
        result = MemberService.get_by_id(self.user1, self.member.pk)
        self.assertIsNone(result)

    def test_display_status_attached_on_get_by_id(self):
        result = MemberService.get_by_id(self.user1, self.member.pk)
        self.assertTrue(hasattr(result, "display_status"))


class MemberServiceCreateDeleteTest(TestCase):

    def setUp(self):
        self.tenant = make_tenant("Gym E")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant)
        self.user = make_user(self.tenant, self.role, "creator@test.com")

    def test_create_member(self):
        member = MemberService.create_member(self.user, {
            "first_name": "New",
            "last_name": "Guy",
            "email": "new@test.com",
        })
        self.assertEqual(member.tenant, self.tenant)
        self.assertEqual(member.created_by, self.user)
        self.assertFalse(member.is_deleted)

    def test_soft_delete_member(self):
        member = make_member(self.tenant, self.user, "Del", "Me", "del@test.com")
        MemberService.soft_delete(member)
        member.refresh_from_db()
        self.assertTrue(member.is_deleted)
        self.assertFalse(Member.objects.filter(pk=member.pk, is_deleted=False).exists())


# ============================================================
# Member Views Tests
# ============================================================

class MemberViewsTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.tenant = make_tenant("ViewGym")
        self.branch = make_branch(self.tenant)
        self.role = make_role(self.tenant, "Admin")

        for module, action in [
            ("members", "view"),
            ("members", "view_member"),
            ("members", "create"),
            ("members", "update"),
            ("members", "delete"),
        ]:
            perm = make_permission(module, action)
            grant_permission(self.role, perm, self.tenant)

        self.user = make_user(self.tenant, self.role, "view@test.com")
        self.member = make_member(self.tenant, self.user, "View", "Test", "view@member.com")
        self.client.login(email="view@test.com", password="testpass123")

    def test_member_list_returns_200(self):
        response = self.client.get(reverse("members:member_list"))
        self.assertEqual(response.status_code, 200)

    def test_member_list_shows_all_tenant_members(self):
        other_user = make_user(self.tenant, self.role, "other@test.com")
        make_member(self.tenant, other_user, "Other", "Person", "other@member.com")
        response = self.client.get(reverse("members:member_list"))
        self.assertContains(response, "Other")

    def test_member_detail_accessible_by_any_staff(self):
        """Regression: staff should see members created by other users."""
        other_user = make_user(self.tenant, self.role, "other2@test.com")
        other_member = make_member(self.tenant, other_user, "Jane", "Doe", "jane@member.com")
        response = self.client.get(reverse("members:member_detail", args=[other_member.pk]))
        self.assertEqual(response.status_code, 200)

    def test_member_create_get(self):
        response = self.client.get(reverse("members:member_create"))
        self.assertEqual(response.status_code, 200)

    def test_member_create_post(self):
        response = self.client.post(reverse("members:member_create"), {
            "first_name": "New",
            "last_name": "Member",
            "email": "newmember@test.com",
            "phone": "1234567890",
            "branches": [str(self.branch.pk)],
        })
        self.assertRedirects(response, reverse("members:member_list"))
        self.assertTrue(Member.objects.filter(email="newmember@test.com").exists())

    def test_member_update_redirects_to_namespaced_detail(self):
        """Regression: member_update must use members:member_detail namespace."""
        self.member.branches.add(self.branch)
        response = self.client.post(reverse("members:member_update", args=[self.member.pk]), {
            "first_name": "Updated",
            "last_name": self.member.last_name,
            "email": self.member.email,
            "phone": "",
            "branches": [str(self.branch.pk)],
        })
        self.assertRedirects(
            response,
            reverse("members:member_detail", args=[self.member.pk])
        )

    def test_unauthenticated_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("members:member_list"))
        self.assertIn(response.status_code, [302, 403])

    def test_member_delete_post_soft_deletes(self):
        response = self.client.post(reverse("members:member_delete", args=[self.member.pk]))
        self.assertRedirects(response, reverse("members:member_list"))
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_deleted)
